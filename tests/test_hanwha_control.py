"""Reset and reboot of Hanwha cameras: HTTPS first, HTTP when HTTPS cannot be used"""
import hashlib
import re
import socket
import threading

import pytest
import requests

from src import event_log
import src.sensor_AIHANWHA as hanwha


class Answer:
    def __init__(self, status):
        self.status_code = status
        self.reason = {200: 'OK', 401: 'Unauthorized', 500: 'Internal Server Error'}[status]
        self.text = 'OK'
        self.ok = status < 400

    def raise_for_status(self):
        if not self.ok:
            raise requests.HTTPError(str(self.status_code), response=self)


def counts_answer(counts):
    answer = Answer(200)
    answer.text = ("Channel.0.LineIndex=1\rChannel.0.LineIndex.1.Name=Ausgang\rChannel.0.LineIndex.1.InCount={}\r"
                   "Channel.0.LineIndex.1.OutCount={}\rChannel.0.LineIndex=2\rChannel.0.LineIndex.2.InCount={}\r"
                   "Channel.0.LineIndex.2.OutCount={}\r").format(*counts)
    return answer


def camera(monkeypatch, https_problem, behaviour, counts=()):
    """Camera whose TLS check and answers per scheme are given; returns it with the list of schemes used.
    `behaviour` gives per scheme one result or a list of results for consecutive commands.
    `counts` are the counter values the camera reports, one entry per query (None: no answer);
    once they are used up the camera does not answer queries any more."""
    cam = hanwha.AI_HANWHA('11', '192.0.2.11', 'KAM11', '2', 'admin', 'pw', '1')
    used = []
    behaviour = {scheme: list(result) if isinstance(result, list) else result for scheme, result in behaviour.items()}
    remaining = list(counts)

    def post(url, **kwargs):
        scheme = url.split(':')[0]
        used.append(scheme)
        result = behaviour[scheme]
        if isinstance(result, list):
            result = result.pop(0)
        if isinstance(result, Exception):
            raise result
        return Answer(result)

    def get(url, **kwargs):
        value = remaining.pop(0) if remaining else None
        if value is None:
            raise requests.exceptions.ConnectionError('keine Antwort')
        return counts_answer(value)
    monkeypatch.setattr(cam.session, 'post', post)
    monkeypatch.setattr(cam.session, 'get', get)
    monkeypatch.setattr(cam, '_https_problem', lambda: https_problem)
    return cam, used


def test_https_is_used_when_the_camera_supports_it(monkeypatch):
    cam, used = camera(monkeypatch, None, {'https': 200, 'http': 200})
    assert cam.reset_sensor_values() is True
    assert used == ['https'] and cam.last_action_error is None


def test_http_is_used_when_the_tls_handshake_fails_and_the_choice_is_remembered(monkeypatch):
    cam, used = camera(monkeypatch, 'keine TLS-Verbindung (Zeitüberschreitung)', {'https': 200, 'http': 200})
    assert cam.reset_sensor_values() is True
    assert used == ['http'], "nothing is sent over HTTPS when the handshake does not work"
    assert cam.reboot_sensor() is True
    assert used == ['http', 'http']
    notes = [e for e in event_log.read_events(1)[0] if e['kind'] == 'info']
    assert len(notes) == 1 and 'über HTTP' in notes[0]['message']


def test_http_is_used_when_the_https_connection_fails(monkeypatch):
    cam, used = camera(monkeypatch, None, {'https': requests.exceptions.ConnectionError('refused'), 'http': 200})
    assert cam.reset_sensor_values() is True
    assert used == ['https', 'http']


def test_an_answered_command_is_never_repeated_over_the_other_scheme(monkeypatch):
    cam, used = camera(monkeypatch, None, {'https': 500, 'http': 200})
    assert cam.reset_sensor_values() is False
    assert used == ['https']
    assert cam.last_action_error == 'Zurücksetzen fehlgeschlagen: HTTP 500 Internal Server Error'


def test_a_sent_command_without_answer_is_never_repeated(monkeypatch):
    """The camera may already have executed it, e.g. a reboot."""
    cam, used = camera(monkeypatch, None, {'https': requests.exceptions.ReadTimeout('read timed out'), 'http': 200})
    assert cam.reboot_sensor() is False
    assert used == ['https']
    assert 'Warten auf die Antwort' in cam.last_action_error


def test_rejected_login_over_http_is_reported(monkeypatch):
    cam, used = camera(monkeypatch, 'keine TLS-Verbindung (Zeitüberschreitung)', {'https': 200, 'http': 401})
    assert cam.reset_sensor_values() is False
    assert cam.last_action_error == 'Zurücksetzen fehlgeschlagen: HTTP 401 Unauthorized'


def test_both_reasons_are_named_when_no_scheme_works(monkeypatch):
    refused = requests.exceptions.ConnectionError('refused')
    cam, used = camera(monkeypatch, 'keine TLS-Verbindung (Zeitüberschreitung)', {'https': refused, 'http': refused})
    assert cam.reset_sensor_values() is False
    assert cam.last_action_error.startswith('Zurücksetzen fehlgeschlagen: HTTPS: keine TLS-Verbindung')
    assert '; HTTP: ' in cam.last_action_error


# ---- with real connections ---------------------------------------------------

@pytest.fixture
def silent_tls_camera():
    """A camera as it was found on site: it accepts the connection, never completes a TLS
    handshake, but answers plain HTTP with digest authentication. One port serves both: a
    connection that starts with a TLS record (first byte 0x16) is left unanswered."""
    md5 = lambda text: hashlib.md5(text.encode()).hexdigest()
    seen, held = [], []
    server = socket.socket()
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(('127.0.0.1', 0))
    server.listen(16)

    def serve():
        while True:
            try:
                connection, _ = server.accept()
            except OSError:
                return
            connection.settimeout(3)
            try:
                if connection.recv(1, socket.MSG_PEEK) == b'\x16':
                    held.append(connection)  # TLS: stay silent
                    continue
                data = b''
                while b'\r\n\r\n' not in data:
                    data += connection.recv(4096)
                head = data.decode('latin-1')
                path = head.split(' ')[1]
                header = re.search(r'Authorization: Digest (.*)\r\n', head)
                if not header:
                    reply = 'HTTP/1.0 401 Unauthorized\r\nWWW-Authenticate: Digest realm="cam", nonce="n1", qop="auth"\r\nContent-Length: 0\r\n\r\n'
                else:
                    p = dict(re.findall(r'(\w+)="?([^",]+)"?', header.group(1)))
                    expected = md5(f"{md5('admin:cam:kam-pw')}:{p['nonce']}:{p['nc']}:{p['cnonce']}:{p['qop']}:{md5('POST:' + p['uri'])}")
                    correct = p.get('response') == expected
                    seen.append((path.split('msubmenu=')[1].split('&')[0], correct))
                    reply = f"HTTP/1.0 {'200 OK' if correct else '401 Unauthorized'}\r\nContent-Length: 2\r\n\r\nOK"
                connection.sendall(reply.encode())
                connection.close()
            except OSError:
                connection.close()
    threading.Thread(target=serve, daemon=True).start()
    yield f"127.0.0.1:{server.getsockname()[1]}", seen
    server.close()
    for connection in held:
        connection.close()


def test_camera_that_never_completes_the_tls_handshake_is_controlled_over_http(silent_tls_camera, monkeypatch):
    """Regression test for the case found on site: requests reports the hanging handshake as a
    timeout of the answer, which looked like a command that had been sent."""
    address, seen = silent_tls_camera
    monkeypatch.setattr(hanwha, 'REQUEST_TIMEOUT', (0.5, 3))
    cam = hanwha.AI_HANWHA('11', address, 'KAM11', '2', 'admin', 'kam-pw', '1')
    assert cam._https_problem() == 'keine TLS-Verbindung (Zeitüberschreitung)'
    assert cam.reset_sensor_values() is True, cam.last_action_error
    assert cam.reboot_sensor() is True, cam.last_action_error
    commands = [entry for entry in seen if entry[0] != 'peoplecount']  # the counters are read before a reset
    assert commands == [('databasereset', True), ('power', True)], "both commands arrived with a correct login"
    assert cam._control_scheme == 'http'


def test_wrong_password_is_reported_by_the_camera(silent_tls_camera, monkeypatch):
    address, seen = silent_tls_camera
    monkeypatch.setattr(hanwha, 'REQUEST_TIMEOUT', (0.5, 3))
    cam = hanwha.AI_HANWHA('11', address, 'KAM11', '2', 'admin', 'falsch', '1')
    assert cam.reset_sensor_values() is False
    assert cam.last_action_error == 'Zurücksetzen fehlgeschlagen: HTTP 401 Unauthorized'


def test_tls_check_reports_a_closed_port():
    probe = socket.socket()
    probe.bind(('127.0.0.1', 0))
    port = probe.getsockname()[1]
    probe.close()  # nothing listens on this port any more
    cam = hanwha.AI_HANWHA('11', f'127.0.0.1:{port}', 'KAM11', '2', 'admin', 'pw', '1')
    assert cam._https_problem().startswith('keine TLS-Verbindung (ConnectionRefusedError')


# ---- Reset with a check of the counters --------------------------------------

TLS_DOWN = 'keine TLS-Verbindung (Zeitüberschreitung)'
CLOSED = requests.exceptions.ConnectionError('RemoteDisconnected')


def test_unconfirmed_reset_is_repeated_once_when_the_counters_are_unchanged(monkeypatch):
    """Seen on site (camera 11, 23:45): the camera closed the connection, the counters stayed at 15 and 35."""
    cam, used = camera(monkeypatch, TLS_DOWN, {'http': [CLOSED, 200]}, counts=[(15, 35, 0, 0), (15, 35, 0, 0)])
    assert cam.reset_sensor_values() is True
    assert used == ['http', 'http'] and cam.last_action_error is None
    notes = [e['message'] for e in event_log.read_events(1)[0] if e['kind'] == 'info']
    assert any('erst beim zweiten Versuch erfolgreich' in note for note in notes)


def test_reset_is_repeated_only_once(monkeypatch):
    cam, used = camera(monkeypatch, TLS_DOWN, {'http': [CLOSED, CLOSED, 200]}, counts=[(15, 35, 0, 0), (16, 35, 0, 0)])
    assert cam.reset_sensor_values() is False
    assert used == ['http', 'http']
    assert 'auch die Wiederholung' in cam.last_action_error and 'erster Versuch' in cam.last_action_error


@pytest.mark.parametrize('before,after', [
    ((15, 35, 0, 0), (0, 0, 0, 0)),      # all zero
    ((15, 35, 2, 1), (1, 0, 0, 0)),      # reset, and one person passed since
    (None, (0, 0, 0, 0)),                # counters before unknown, zero afterwards
])
def test_unconfirmed_reset_is_not_repeated_when_the_counters_show_it_was_executed(monkeypatch, before, after):
    cam, used = camera(monkeypatch, TLS_DOWN, {'http': [CLOSED, 200]}, counts=[before, after])
    assert cam.reset_sensor_values() is True
    assert used == ['http'], "a second reset would delete counts made after the first one"
    assert cam.last_action_error is None
    notes = [e['message'] for e in event_log.read_events(1)[0] if e['kind'] == 'info']
    assert any('nicht bestätigt' in note and 'zurückgesetzt' in note for note in notes)


def test_unconfirmed_reset_is_not_repeated_when_the_counters_cannot_be_read(monkeypatch):
    cam, used = camera(monkeypatch, TLS_DOWN, {'http': [CLOSED, 200]}, counts=[(15, 35, 0, 0), None])
    assert cam.reset_sensor_values() is False
    assert used == ['http'] and 'nicht lesbar, daher keine Wiederholung' in cam.last_action_error


def test_unknown_counters_before_and_values_afterwards_lead_to_one_repetition(monkeypatch):
    cam, used = camera(monkeypatch, TLS_DOWN, {'http': [CLOSED, 200]}, counts=[None, (15, 35, 0, 0)])
    assert cam.reset_sensor_values() is True and used == ['http', 'http']


def test_confirmed_reset_and_reboot_are_never_repeated(monkeypatch):
    cam, used = camera(monkeypatch, None, {'https': 200}, counts=[(15, 35, 0, 0), (15, 35, 0, 0)])
    assert cam.reset_sensor_values() is True and used == ['https']
    cam, used = camera(monkeypatch, TLS_DOWN, {'http': [CLOSED, 200]}, counts=[(15, 35, 0, 0), (15, 35, 0, 0)])
    assert cam.reboot_sensor() is False and used == ['http'], "a reboot cannot be checked and is not repeated"
