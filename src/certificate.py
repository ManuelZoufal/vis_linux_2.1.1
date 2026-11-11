"""
TLS certificate of the web server: expiry check and automatic renewal

Expiry
    The certificate in use is read at startup and after every renewal.

Renewal
    When the certificate is valid for CERT_RENEW_DAYS (default 1) or less, a
    new key and certificate are created with the openssl command line tool
    and loaded into the running web server, without a restart.
    - If the CA files (CERT_CA_CERT, CERT_CA_KEY; default ca.crt and ca.key)
      exist, the certificate is issued by that CA, so devices that trust the
      CA accept it without any change.
    - Otherwise it is self-signed. Devices then show a warning until the new
      certificate is stored as trusted on each of them.
    Subject and alternative names are taken from the certificate that is
    replaced. The previous files are kept as *.alt.
"""
import logging
import os
import secrets
import shutil
import socket
import ssl
import subprocess
import tempfile
import threading
import time
from datetime import datetime

from src import event_log

CERT_FILE = 'Webserver_IP.crt'
KEY_FILE = 'Webserver_IP.pem'
WARN_DAYS = int(os.environ.get('CERT_WARN_DAYS', 30))

AUTO_RENEW = os.environ.get('CERT_AUTO_RENEW', 'true').strip().lower() in ('1', 'true', 'yes')
RENEW_DAYS = float(os.environ.get('CERT_RENEW_DAYS', 1))     # renew when valid for this many days or less
VALID_DAYS = int(os.environ.get('CERT_VALID_DAYS', 365))     # validity of a new certificate
CA_CERT_FILE = os.environ.get('CERT_CA_CERT', 'ca.crt')
CA_KEY_FILE = os.environ.get('CERT_CA_KEY', 'ca.key')
CHECK_SECONDS = 3600                                         # how often the renewal thread looks at the certificate

METHOD_CA = 'ca'
METHOD_SELF_SIGNED = 'self-signed'
METHOD_LABELS = {METHOD_CA: 'von der eigenen CA ausgestellt', METHOD_SELF_SIGNED: 'selbstsigniert'}

_context = None               # SSL context of the running web server
_renew_lock = threading.Lock()

_loaded = {'not_after': None, 'names': [], 'mtime': None, 'error': None}


def _read_not_after(path):
    """
    Read the end of validity and the alternative names of a certificate

    Returns:
    tuple: (seconds since epoch, list of names)
    """
    try:
        info = ssl._ssl._test_decode_cert(path)  # standard library, no extra package needed
        names = [value for _kind, value in info.get('subjectAltName', ())]
        return ssl.cert_time_to_seconds(info['notAfter']), names
    except Exception:
        # Fallback: the openssl command line tool
        output = subprocess.run(['openssl', 'x509', '-in', path, '-noout', '-enddate'],
                                capture_output=True, text=True, timeout=10, check=True).stdout
        return ssl.cert_time_to_seconds(output.strip().split('=', 1)[1]), []


def load():
    """Read the certificate file; called once at startup"""
    try:
        _loaded['not_after'], _loaded['names'] = _read_not_after(CERT_FILE)
        _loaded['mtime'] = os.path.getmtime(CERT_FILE)
        _loaded['error'] = None
    except Exception as e:
        _loaded.update(not_after=None, names=[], mtime=None, error=f"{type(e).__name__}: {e}")
        logging.warning(f"Certificate {CERT_FILE} could not be read: {_loaded['error']}")
    return get_status()


def _renewal_info(not_after):
    """Part of the status that describes the automatic renewal"""
    method = renewal_method()
    info = {'auto_renew': AUTO_RENEW, 'renew_method': method, 'renew_at': None}
    if not AUTO_RENEW:
        info['renew_message'] = "Automatische Erneuerung ist abgeschaltet (CERT_AUTO_RENEW)."
        return info
    how = (f"von der CA ({CA_CERT_FILE})" if method == METHOD_CA
           else f"selbstsigniert, weil {CA_CERT_FILE} und {CA_KEY_FILE} nicht vorhanden sind")
    if not_after is None:
        info['renew_message'] = f"Automatische Erneuerung: bei der nächsten Prüfung, {how}."
    else:
        info['renew_at'] = datetime.fromtimestamp(not_after - RENEW_DAYS * 86400).strftime('%Y-%m-%d %H:%M')
        info['renew_message'] = f"Automatische Erneuerung ab {info['renew_at']}, {how}."
    return info


def get_status():
    """
    Get the state of the certificate the server is using

    Returns:
    dict: state ('ok', 'warning', 'expired', 'unknown'), valid_until, days_left,
          names, restart_needed (file changed since startup) and a message for the user interface
    """
    if _loaded['not_after'] is None:
        return {'state': 'unknown', 'valid_until': None, 'days_left': None, 'seconds_left': None, 'names': [],
                'restart_needed': False, 'message': 'Das Ablaufdatum des Zertifikats konnte nicht gelesen werden.',
                **_renewal_info(None)}

    seconds_left = _loaded['not_after'] - time.time()
    days_left = int(seconds_left // 86400)
    valid_until = datetime.fromtimestamp(_loaded['not_after']).strftime('%Y-%m-%d %H:%M')
    try:
        restart_needed = os.path.getmtime(CERT_FILE) != _loaded['mtime']
    except OSError:
        restart_needed = False

    if seconds_left <= 0:
        state = 'expired'
        message = f"Das Zertifikat ist seit {valid_until} abgelaufen ({-days_left} Tage)."
    elif days_left < WARN_DAYS:
        state = 'warning'
        message = f"Das Zertifikat läuft am {valid_until} ab (noch {days_left} Tage)."
    else:
        state = 'ok'
        message = f"Zertifikat gültig bis {valid_until} (noch {days_left} Tage)."
    if restart_needed:
        message += " Die Zertifikatsdatei wurde geändert und wird bei der nächsten Prüfung geladen."

    return {'state': state, 'valid_until': valid_until, 'days_left': days_left, 'seconds_left': seconds_left,
            'names': list(_loaded['names']), 'restart_needed': restart_needed, 'message': message,
            **_renewal_info(_loaded['not_after'])}


# ---- Renewal -----------------------------------------------------------------

def create_ssl_context():
    """
    Create the SSL context for the web server and keep it, so a renewed
    certificate can be loaded into the running server

    Returns:
    ssl.SSLContext: Context with the current certificate
    """
    global _context
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(CERT_FILE, KEY_FILE)
    _context = context
    return context


def renewal_method():
    """How a new certificate would be issued right now: by the CA if its files exist, otherwise self-signed"""
    return METHOD_CA if os.path.isfile(CA_CERT_FILE) and os.path.isfile(CA_KEY_FILE) else METHOD_SELF_SIGNED


def _openssl(*args):
    """Run the openssl command line tool; raises RuntimeError with its message on failure"""
    try:
        result = subprocess.run(['openssl', *args], capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
    except FileNotFoundError:
        raise RuntimeError("Das Programm openssl ist auf dem Server nicht installiert")
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"openssl {args[0]} hat nicht geantwortet")
    if result.returncode != 0:
        raise RuntimeError(f"openssl {args[0]} ist fehlgeschlagen: {event_log.shorten(result.stderr or result.stdout, 200)}")
    return result.stdout


SUBJECT_NAMES = {'countryName': 'C', 'stateOrProvinceName': 'ST', 'localityName': 'L', 'organizationName': 'O',
                 'organizationalUnitName': 'OU', 'commonName': 'CN', 'emailAddress': 'emailAddress'}
ALT_NAME_KINDS = {'IP Address': 'IP', 'DNS': 'DNS'}


def _local_address():
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(('10.254.254.254', 1))  # nothing is sent, this only selects the outgoing interface
        return probe.getsockname()[0]
    except OSError:
        return '127.0.0.1'
    finally:
        probe.close()


def _identity():
    """
    Subject and alternative names for a new certificate, taken from the current
    one. Without a readable certificate the host name and address of the server are used.

    Returns:
    tuple: (subject in openssl notation, list of alternative names like "IP:10.0.0.1")
    """
    subject, names = '', []
    try:
        info = ssl._ssl._test_decode_cert(CERT_FILE)
        for rdn in info.get('subject', ()):
            for key, value in rdn:
                if key in SUBJECT_NAMES:
                    escaped = value.replace('\\', '\\\\').replace('/', '\\/')
                    subject += f"/{SUBJECT_NAMES[key]}={escaped}"
        names = [f"{ALT_NAME_KINDS[kind]}:{value}" for kind, value in info.get('subjectAltName', ()) if kind in ALT_NAME_KINDS]
    except Exception:
        pass
    if not subject:
        subject = f"/CN={socket.gethostname()}"
    if not names:
        names = [f"IP:{_local_address()}", f"DNS:{socket.gethostname()}"]
    return subject, names


def renew(reason):
    """
    Create a new key and certificate and put them into use

    Nothing is replaced unless the new certificate has been verified: it must
    match the new key, be loadable by the web server and, when issued by the
    CA, chain to it.

    Args:
    reason (str): Why the certificate is renewed, for the event log

    Returns:
    dict: The new certificate status (see get_status)

    Raises:
    RuntimeError: If the certificate could not be created; the old one stays in use
    """
    with _renew_lock:
        method = renewal_method()
        subject, names = _identity()
        days = VALID_DAYS
        work = tempfile.mkdtemp(prefix='.cert-', dir=os.path.dirname(os.path.abspath(CERT_FILE)))  # same file system, so the final rename is atomic
        try:
            key, request, certificate, extensions = (os.path.join(work, name) for name in ('key.pem', 'request.csr', 'cert.crt', 'ext.cnf'))
            _openssl('genrsa', '-out', key, '2048')
            os.chmod(key, 0o600)
            _openssl('req', '-new', '-key', key, '-out', request, '-subj', subject)
            alt_names = ', '.join(names)
            if method == METHOD_CA:
                ca_remaining = (_read_not_after(CA_CERT_FILE)[0] - time.time()) / 86400
                if ca_remaining < 1:
                    raise RuntimeError(f"Das CA-Zertifikat {CA_CERT_FILE} ist abgelaufen oder läuft heute ab")
                days = max(1, min(days, int(ca_remaining)))  # never valid longer than the CA itself
                with open(extensions, 'w', encoding='utf-8') as file:
                    file.write(f"subjectAltName = {alt_names}\nbasicConstraints = CA:FALSE\n"
                               "keyUsage = digitalSignature, keyEncipherment\nextendedKeyUsage = serverAuth\n")
                sign = ['x509', '-req', '-in', request, '-CA', CA_CERT_FILE, '-CAkey', CA_KEY_FILE,
                        '-set_serial', '0x' + secrets.token_hex(16), '-out', certificate,
                        '-days', str(days), '-sha256', '-extfile', extensions]
                if os.environ.get('CERT_CA_KEY_PASSWORD'):
                    sign += ['-passin', 'env:CERT_CA_KEY_PASSWORD']
                _openssl(*sign)
                _openssl('verify', '-CAfile', CA_CERT_FILE, certificate)
            else:
                # Like "openssl req -x509": the certificate is its own issuer and can be stored as trusted on a device
                with open(extensions, 'w', encoding='utf-8') as file:
                    file.write(f"subjectAltName = {alt_names}\nbasicConstraints = CA:TRUE\n")
                _openssl('x509', '-req', '-in', request, '-signkey', key, '-set_serial', '0x' + secrets.token_hex(16),
                         '-out', certificate, '-days', str(days), '-sha256', '-extfile', extensions)

            if _openssl('x509', '-in', certificate, '-noout', '-pubkey') != _openssl('pkey', '-in', key, '-pubout'):
                raise RuntimeError("Das neue Zertifikat passt nicht zum neuen Schlüssel")
            ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER).load_cert_chain(certificate, key)  # the web server must be able to load it

            # Keep the previous files, then put the new ones in place
            for current in (CERT_FILE, KEY_FILE):
                if os.path.exists(current):
                    shutil.copy2(current, current + '.alt')
            os.replace(key, KEY_FILE)
            os.replace(certificate, CERT_FILE)
        finally:
            shutil.rmtree(work, ignore_errors=True)

        if _context is not None:
            _context.load_cert_chain(CERT_FILE, KEY_FILE)  # new connections get the new certificate, no restart needed
        status = load()
        message = (f"Zertifikat erneuert ({METHOD_LABELS[method]}), gültig bis {status['valid_until']}. "
                   f"Anlass: {reason}. Namen: {', '.join(names)}")
        logging.info(f"[VIS] {message}")
        event_log.event('info', 'CertificateThread', message, 'Zertifikat')
        return status


def check():
    """
    Look at the certificate and renew it if it is about to expire; also load a
    certificate file that was replaced by hand

    Returns:
    str: Short description of the state, for the thread status
    """
    status = get_status()
    if status.get('restart_needed') and _context is not None:
        _context.load_cert_chain(CERT_FILE, KEY_FILE)
        status = load()
        event_log.event('info', 'CertificateThread', f"Geänderte Zertifikatsdatei geladen, gültig bis {status['valid_until']}", 'Zertifikat')
    due = status['state'] == 'unknown' or status['seconds_left'] <= RENEW_DAYS * 86400
    if AUTO_RENEW and due:
        status = renew("Datei nicht lesbar" if status['state'] == 'unknown' else f"nur noch {max(status['seconds_left'], 0) / 3600:.0f} Stunden gültig")
    return status['message']


def renewal_thread(interval):
    """
    Check the certificate regularly

    Args:
    interval (int): Interval in seconds
    """
    from src import thread_status  # imported here: thread_status is not needed by the rest of this module
    while True:
        try:
            thread_status.report_success(check())
        except Exception as e:
            thread_status.report_error(f"Zertifikat konnte nicht erneuert werden: {e}")
        time.sleep(interval)
