"""Navigator: token reuse, throttling after failures, uploads"""
import os
import time

import pytest

from conftest import WORK, run_in_thread

from src import event_log, navigator, thread_status
from src.database import save_sensor_values


class Reply:
    def __init__(self, status, body=None):
        self.status_code = status
        self.reason = {200: 'OK', 201: 'Created', 401: 'Unauthorized'}.get(status, '')
        self._body = body or {}
        self.text = str(self._body)

    def json(self):
        return self._body


@pytest.fixture
def fake_navigator(monkeypatch):
    """Stands in for Navigator: counts token requests and uploads, behaviour is adjustable"""
    state = {'token_requests': 0, 'uploads': [], 'credentials': [], 'accept': True, 'expires_in': 3600, 'rejected_tokens': set()}

    def post(url, headers=None, **kwargs):
        if url.endswith('/oauth/token'):
            state['token_requests'] += 1
            state['credentials'].append(headers['Authorization'])
            if not state['accept']:
                return Reply(401, {'error': 'unauthorized'})
            body = {'access_token': f"TOKEN-{state['token_requests']}"}
            if state['expires_in'] is not None:
                body['expires_in'] = state['expires_in']
            return Reply(200, body)
        token = headers['Authorization'].split()[1]
        if token in state['rejected_tokens']:
            return Reply(401)
        state['uploads'].append((url.split('/meter/')[1].split('/')[0], token))
        return Reply(201)
    monkeypatch.setattr(navigator.requests, 'post', post)
    return state


def upload_all(count=12):
    return [navigator.upload_data_to_navigator(str(1000 + index), 5, f'S{index}') for index in range(count)]


def test_one_token_is_reused_for_all_uploads(fake_navigator):
    """A token used to be requested for every sensor and minute."""
    assert all(upload_all()) and all(upload_all())
    assert fake_navigator['token_requests'] == 1
    assert len(fake_navigator['uploads']) == 24 and {token for _, token in fake_navigator['uploads']} == {'TOKEN-1'}


def test_token_is_renewed_shortly_before_it_expires(fake_navigator, monkeypatch):
    upload_all(1)
    real_time = time.time
    monkeypatch.setattr(navigator.time, 'time', lambda: real_time() + 3600 - navigator.TOKEN_EXPIRY_MARGIN + 1)
    upload_all(1)
    assert fake_navigator['token_requests'] == 2 and fake_navigator['uploads'][-1][1] == 'TOKEN-2'


def test_token_without_lifetime_is_used_for_one_cycle(fake_navigator, monkeypatch):
    fake_navigator['expires_in'] = None
    upload_all()
    assert fake_navigator['token_requests'] == 1
    real_time = time.time
    monkeypatch.setattr(navigator.time, 'time', lambda: real_time() + navigator.TOKEN_DEFAULT_LIFETIME + 1)
    upload_all()
    assert fake_navigator['token_requests'] == 2


def test_rejected_token_is_replaced_once(fake_navigator):
    upload_all(1)
    fake_navigator['rejected_tokens'] = {'TOKEN-1'}
    assert navigator.upload_data_to_navigator('1001', 5, 'S1') is True
    assert fake_navigator['token_requests'] == 2 and fake_navigator['uploads'][-1][1] == 'TOKEN-2'


def test_changed_credentials_request_a_new_token(fake_navigator):
    upload_all(1)
    os.environ['NAVIGATOR_PASSWORD'] = 'neues-pw'
    upload_all(1)
    assert fake_navigator['token_requests'] == 2
    assert fake_navigator['credentials'][0] != fake_navigator['credentials'][1]


def test_token_requests_are_throttled_after_repeated_failures(fake_navigator, monkeypatch):
    """With an expired password a request was sent every minute."""
    fake_navigator['accept'] = False
    assert [bool(navigator.get_token()) for _ in range(12)] == [False] * 12
    assert fake_navigator['token_requests'] == navigator.BACKOFF_AFTER_FAILURES
    assert navigator.last_token_error() == 'HTTP 401 Unauthorized' and navigator.retry_time() is not None
    real_time = time.time
    monkeypatch.setattr(navigator.time, 'time', lambda: real_time() + navigator.RETRY_MINUTES * 60 + 1)
    navigator.get_token()
    navigator.get_token()
    assert fake_navigator['token_requests'] == navigator.BACKOFF_AFTER_FAILURES + 1, "one attempt per waiting period"


def test_new_credentials_end_the_throttling_at_once(fake_navigator):
    fake_navigator['accept'] = False
    for _ in range(8):
        navigator.get_token()
    fake_navigator['accept'] = True
    os.environ['NAVIGATOR_PASSWORD'] = 'neues-pw'
    assert navigator.get_token() == f"TOKEN-{navigator.BACKOFF_AFTER_FAILURES + 1}"
    assert navigator.retry_time() is None
    messages = [e['message'] for e in event_log.read_events(1, 'NavigatorUploadThread')[0]]
    assert any('nur noch alle' in m for m in messages) and any('wieder erhalten' in m for m in messages)


def test_successful_connection_test_ends_the_throttling(fake_navigator):
    fake_navigator['accept'] = False
    for _ in range(8):
        navigator.get_token()
    fake_navigator['accept'] = True
    assert navigator.create_OAUTH_token()  # what the button on the admin page does
    assert navigator.retry_time() is None


def test_missing_credentials_send_nothing(fake_navigator):
    os.environ['NAVIGATOR_USERNAME'] = ''
    assert navigator.get_token() is False
    assert fake_navigator['token_requests'] == 0
    assert navigator.last_token_error() == 'Benutzername oder Passwort nicht hinterlegt'


def test_sensor_without_datapoint_is_not_uploaded(fake_navigator):
    assert [navigator.upload_data_to_navigator(value, 5, 'S') for value in ('', None, 'N/A', '  ')] == [False] * 4
    assert fake_navigator['token_requests'] == 0 and fake_navigator['uploads'] == []


def one_upload_cycle(monkeypatch):
    class Stop(BaseException):
        pass
    thread_status.register('NavigatorUploadThread', 'Navigator-Upload', 60)

    def body():
        thread_status.bind()
        monkeypatch.setattr(navigator.time, 'sleep', lambda seconds: (_ for _ in ()).throw(Stop()))
        with pytest.raises(Stop):
            navigator.navigator_thread(60)
        return next(t for t in thread_status.snapshot() if t['name'] == 'NavigatorUploadThread')
    return run_in_thread('NavigatorUploadThread', body)


def test_upload_cycle_skips_sensors_without_datapoint(fake_navigator, sensors, monkeypatch):
    for sensor in sensors.values():
        save_sensor_values(sensor)  # sensor 10 has no datapoint
    status = one_upload_cycle(monkeypatch)
    assert status['detail'] == '3 Uploads, 1 ohne Datenpunkt übersprungen' and status['error_count'] == 0
    assert sorted(datapoint for datapoint, _ in fake_navigator['uploads']) == ['1001', '1002', '1003']
    assert fake_navigator['token_requests'] == 1


def test_upload_cycle_without_token_sends_one_request_and_names_the_reason(fake_navigator, sensors, monkeypatch):
    fake_navigator['accept'] = False
    for sensor in sensors.values():
        save_sensor_values(sensor)
    status = one_upload_cycle(monkeypatch)
    assert fake_navigator['token_requests'] == 1 and fake_navigator['uploads'] == []
    assert status['last_error'].startswith('Kein Token von Navigator erhalten: HTTP 401 Unauthorized')


def test_detail_log_contains_neither_token_nor_password(fake_navigator):
    name = event_log.start_detail(15, 'navigator')
    navigator.upload_data_to_navigator('1001', 7, 'S1')
    text = (WORK / 'logs' / name).read_text(encoding='utf-8')
    assert '/meter/1001/readings | HTTP 201' in text and 'Wert 7' in text
    assert 'TOKEN-1' not in text and 'nav-pw' not in text
