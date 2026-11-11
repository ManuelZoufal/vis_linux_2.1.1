"""Automatic certificate management: renewal by the own CA or self-signed, threshold, loading without restart.
The certificates are created with the real openssl program, in a temporary directory."""
import os
import socket
import ssl
import subprocess
import threading
import time

import pytest

from conftest import client_for, run_in_thread
from src import certificate, event_log, thread_status

SUBJECT = '/C=DE/O=Testbetrieb/CN=vis-test'
ALT_NAMES = 'IP:10.1.2.3, DNS:vis.example'


def openssl(*args):
    return subprocess.run(['openssl', *args], capture_output=True, text=True, check=True).stdout


def decode(path):
    return ssl._ssl._test_decode_cert(str(path))


def make_certificate(directory, days):
    openssl('req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', str(days), '-subj', SUBJECT,
            '-addext', f'subjectAltName = {ALT_NAMES}',
            '-keyout', str(directory / 'Webserver_IP.pem'), '-out', str(directory / 'Webserver_IP.crt'))


def make_ca(directory, days=3650):
    openssl('req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', str(days), '-subj', '/O=Testbetrieb/CN=Test-CA',
            '-keyout', str(directory / 'ca.key'), '-out', str(directory / 'ca.crt'))


@pytest.fixture
def files(tmp_path, monkeypatch):
    """A directory with a certificate that is valid for 100 days; the module works on these files"""
    for name, file in (('CERT_FILE', 'Webserver_IP.crt'), ('KEY_FILE', 'Webserver_IP.pem'),
                       ('CA_CERT_FILE', 'ca.crt'), ('CA_KEY_FILE', 'ca.key')):
        monkeypatch.setattr(certificate, name, str(tmp_path / file))
    monkeypatch.setattr(certificate, 'AUTO_RENEW', True)
    monkeypatch.setattr(certificate, 'RENEW_DAYS', 1)
    monkeypatch.setattr(certificate, 'VALID_DAYS', 365)
    make_certificate(tmp_path, 100)
    certificate.load()
    return tmp_path


def content(directory):
    return {name: (directory / name).read_bytes() for name in ('Webserver_IP.crt', 'Webserver_IP.pem')}


def test_without_ca_files_the_new_certificate_is_self_signed_and_keeps_names(files):
    before = content(files)
    status = certificate.renew('Test')
    info = decode(files / 'Webserver_IP.crt')
    assert info['issuer'] == info['subject']
    assert dict(pair[0] for pair in info['subject']) == {'countryName': 'DE', 'organizationName': 'Testbetrieb', 'commonName': 'vis-test'}
    assert info['subjectAltName'] == (('IP Address', '10.1.2.3'), ('DNS', 'vis.example'))
    assert status['renew_method'] == 'self-signed' and 364 <= status['days_left'] <= 365
    after = content(files)
    assert after['Webserver_IP.crt'] != before['Webserver_IP.crt'] and after['Webserver_IP.pem'] != before['Webserver_IP.pem']
    # The previous files are kept, the key is only readable by its owner, nothing temporary is left
    assert (files / 'Webserver_IP.crt.alt').read_bytes() == before['Webserver_IP.crt']
    assert (files / 'Webserver_IP.pem.alt').read_bytes() == before['Webserver_IP.pem']
    assert os.stat(files / 'Webserver_IP.pem').st_mode & 0o777 == 0o600
    assert not [name for name in os.listdir(files) if name.startswith('.cert-')]
    ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER).load_cert_chain(str(files / 'Webserver_IP.crt'), str(files / 'Webserver_IP.pem'))


def test_with_ca_files_the_certificate_is_issued_by_the_ca(files):
    make_ca(files)
    status = certificate.renew('Test')
    info = decode(files / 'Webserver_IP.crt')
    assert dict(pair[0] for pair in info['issuer'])['commonName'] == 'Test-CA'
    assert dict(pair[0] for pair in info['subject'])['commonName'] == 'vis-test'
    assert info['subjectAltName'] == (('IP Address', '10.1.2.3'), ('DNS', 'vis.example'))
    assert status['renew_method'] == 'ca'
    # A client that trusts only the CA accepts the certificate for the address in it
    assert 'OK' in openssl('verify', '-CAfile', str(files / 'ca.crt'), '-verify_ip', '10.1.2.3', '-purpose', 'sslserver',
                           str(files / 'Webserver_IP.crt'))
    text = openssl('x509', '-in', str(files / 'Webserver_IP.crt'), '-noout', '-text')
    assert 'CA:FALSE' in text and 'TLS Web Server Authentication' in text


def test_certificate_of_the_ca_never_outlives_the_ca(files):
    make_ca(files, days=30)
    status = certificate.renew('Test')
    assert 28 <= status['days_left'] <= 30


def test_failing_ca_keeps_the_old_certificate_and_does_not_fall_back_to_self_signed(files):
    make_ca(files)
    (files / 'ca.key').write_text('kein Schlüssel')
    before = content(files)
    with pytest.raises(RuntimeError, match='openssl x509 ist fehlgeschlagen'):
        certificate.renew('Test')
    assert content(files) == before
    assert not (files / 'Webserver_IP.crt.alt').exists()
    assert not [name for name in os.listdir(files) if name.startswith('.cert-')]


def test_ca_that_expires_today_is_reported(files):
    make_ca(files, days=1)
    with pytest.raises(RuntimeError, match='CA-Zertifikat'):
        certificate.renew('Test')


@pytest.mark.parametrize('days,auto,renewed', [
    (100, True, False),   # far from expiry
    (2, True, False),     # more than one day left
    (1, True, True),      # one day or less
    (1, False, False),    # switched off
])
def test_renewal_happens_only_when_one_day_or_less_is_left(files, monkeypatch, days, auto, renewed):
    make_certificate(files, days)
    certificate.load()
    monkeypatch.setattr(certificate, 'AUTO_RENEW', auto)
    before = content(files)
    message = certificate.check()
    assert (content(files) != before) is renewed
    if renewed:
        assert 'noch 364 Tage' in message or 'noch 365 Tage' in message
        events, _ = event_log.read_events()
        assert events[0]['source'] == 'CertificateThread' and 'Zertifikat erneuert (selbstsigniert)' in events[0]['message']
        assert 'IP:10.1.2.3' in events[0]['message']


def test_status_names_time_and_kind_of_the_next_renewal(files, monkeypatch):
    status = certificate.get_status()
    expected = time.strftime('%Y-%m-%d %H:%M', time.localtime(certificate._loaded['not_after'] - 86400))
    assert status['renew_at'] == expected and expected in status['renew_message'] and 'selbstsigniert' in status['renew_message']
    make_ca(files)
    assert 'von der CA' in certificate.get_status()['renew_message']
    monkeypatch.setattr(certificate, 'AUTO_RENEW', False)
    assert 'abgeschaltet' in certificate.get_status()['renew_message'] and certificate.get_status()['renew_at'] is None


def test_missing_certificate_is_created_with_host_name_and_address(files):
    os.remove(files / 'Webserver_IP.crt')
    os.remove(files / 'Webserver_IP.pem')
    certificate.load()
    assert certificate.get_status()['state'] == 'unknown'
    certificate.check()
    info = decode(files / 'Webserver_IP.crt')
    assert dict(pair[0] for pair in info['subject'])['commonName'] == socket.gethostname()
    kinds = [kind for kind, _ in info['subjectAltName']]
    assert kinds == ['IP Address', 'DNS']
    assert certificate.get_status()['state'] == 'ok'


def served_certificate(port):
    return ssl.PEM_cert_to_DER_cert(ssl.get_server_certificate(('127.0.0.1', port)))


@pytest.fixture
def tls_server(files):
    """A TLS server that uses the context of the module, like the web server does"""
    context = certificate.create_ssl_context()
    listener = socket.create_server(('127.0.0.1', 0))
    listener.settimeout(5)
    stop = threading.Event()

    def serve():
        while not stop.is_set():
            try:
                connection, _ = listener.accept()
            except OSError:
                continue
            try:
                context.wrap_socket(connection, server_side=True).close()
            except OSError:
                pass

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    yield listener.getsockname()[1]
    stop.set()
    listener.close()


def der(path):
    return ssl.PEM_cert_to_DER_cert(path.read_text())


def test_running_server_presents_the_new_certificate_without_restart(files, tls_server):
    old = der(files / 'Webserver_IP.crt')
    assert served_certificate(tls_server) == old
    certificate.renew('Test')
    new = der(files / 'Webserver_IP.crt')
    assert new != old and served_certificate(tls_server) == new


def test_certificate_replaced_by_hand_is_loaded_at_the_next_check(files, tls_server):
    old = der(files / 'Webserver_IP.crt')
    make_certificate(files, 50)
    os.utime(files / 'Webserver_IP.crt', (time.time() + 5, time.time() + 5))  # file systems with coarse time stamps
    assert served_certificate(tls_server) == old
    certificate.check()
    assert served_certificate(tls_server) == der(files / 'Webserver_IP.crt') != old
    assert 49 <= certificate.get_status()['days_left'] <= 50 and certificate.get_status()['restart_needed'] is False


def test_thread_reports_a_failed_renewal(files, monkeypatch):
    make_certificate(files, 1)
    certificate.load()
    make_ca(files)
    (files / 'ca.key').write_text('kein Schlüssel')

    class Stop(Exception):
        pass

    def stop(_seconds):
        raise Stop

    monkeypatch.setattr(certificate.time, 'sleep', stop)
    thread_status.register('CertificateThread', 'Zertifikat', 3600)

    def run():
        thread_status.bind()
        with pytest.raises(Stop):
            certificate.renewal_thread(3600)

    run_in_thread('CertificateThread', run)
    entry = thread_status.snapshot()[0]
    assert entry['error_count'] == 1 and 'Zertifikat konnte nicht erneuert werden' in entry['last_error']
    events, _ = event_log.read_events()
    assert events[0]['kind'] == 'error' and events[0]['source'] == 'CertificateThread'


def test_button_renews_for_administrators_only(files, admin, anonymous):
    before = content(files)
    assert anonymous.post('/api/certificate/renew').status_code == 401
    assert client_for('Benutzer').post('/api/certificate/renew').status_code == 403
    assert content(files) == before
    response = admin.post('/api/certificate/renew')
    assert response.status_code == 200 and response.get_json()['certificate']['state'] == 'ok'
    assert content(files) != before
    assert 'Zertifikat erneuert durch Benutzer-ID' in admin.get('/api/logs').get_data(as_text=True)
    page = admin.get('/logs').get_data(as_text=True)
    assert 'Zertifikat jetzt erneuern' in page


def test_failed_manual_renewal_is_answered_with_the_reason(files, admin):
    make_ca(files)
    (files / 'ca.key').write_text('kein Schlüssel')
    response = admin.post('/api/certificate/renew')
    assert response.status_code == 500 and 'openssl x509 ist fehlgeschlagen' in response.get_json()['error']
