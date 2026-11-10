"""
Expiry check for the TLS certificate of the web server

The certificate is read once when the application starts, because that is
the certificate the server actually uses until the next restart.
"""
import logging
import os
import ssl
import subprocess
import time
from datetime import datetime

CERT_FILE = 'Webserver_IP.crt'
KEY_FILE = 'Webserver_IP.pem'
WARN_DAYS = int(os.environ.get('CERT_WARN_DAYS', 30))

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


def get_status():
    """
    Get the state of the certificate the server is using

    Returns:
    dict: state ('ok', 'warning', 'expired', 'unknown'), valid_until, days_left,
          names, restart_needed (file changed since startup) and a message for the user interface
    """
    if _loaded['not_after'] is None:
        return {'state': 'unknown', 'valid_until': None, 'days_left': None, 'names': [], 'restart_needed': False,
                'message': 'Das Ablaufdatum des Zertifikats konnte nicht gelesen werden.'}

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
        message += " Die Zertifikatsdatei wurde seit dem Start geändert; sie wird erst nach einem Neustart verwendet."

    return {'state': state, 'valid_until': valid_until, 'days_left': days_left, 'names': list(_loaded['names']),
            'restart_needed': restart_needed, 'message': message}
