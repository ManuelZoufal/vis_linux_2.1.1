"""Thread status, short error texts, event log and detail log"""
import datetime
import os
import threading
import time

import pytest
import requests
from http.client import RemoteDisconnected
from urllib3.exceptions import ConnectTimeoutError, MaxRetryError, ProtocolError

from conftest import WORK, run_in_thread

from src import event_log, sensor as sensor_module, thread_status
from src.sensor_base import short_reason

HTML_PAGE = '<!DOCTYPE html PUBLIC\n"-//W3C//DTD XHTML 1.0 Transitional//EN">\n<html><head><title>500</title></head>' + '<p>x</p>\n' * 40


class Answer:
    def __init__(self, status, reason, text):
        self.status_code, self.reason, self.text, self.ok = status, reason, text, status < 400

    def __bool__(self):  # like requests.Response: falsy for error statuses
        return self.ok


def test_short_reasons_for_the_failures_seen_on_site():
    assert short_reason(requests.HTTPError('500 Server Error'), Answer(500, 'Internal Server Error', HTML_PAGE)) == 'HTTP 500 Internal Server Error'
    timeout = requests.exceptions.ConnectTimeout(MaxRetryError(None, '/x', ConnectTimeoutError(None, 'Connection to 192.0.2.1 timed out.')))
    assert short_reason(timeout) == 'Zeitüberschreitung beim Verbindungsaufbau'
    aborted = requests.exceptions.ConnectionError(ProtocolError('Connection aborted.', RemoteDisconnected('Remote end closed connection without response')))
    assert short_reason(aborted) == 'RemoteDisconnected: Remote end closed connection without response'
    assert short_reason(requests.exceptions.ReadTimeout('x')) == 'Zeitüberschreitung beim Warten auf die Antwort'
    assert short_reason(None) == 'unbekannter Fehler'


def test_failed_query_gives_a_short_reason_instead_of_the_answer_page(sensors, monkeypatch):
    """A sensor answering HTTP 500 with a HTML page once filled the status with 30 lines per sensor."""
    answer = Answer(500, 'Internal Server Error', HTML_PAGE)
    answer.raise_for_status = lambda: (_ for _ in ()).throw(requests.HTTPError('500', response=answer))
    monkeypatch.setattr(sensors['2'].session, 'get', lambda *a, **kw: answer)
    assert sensors['2'].fetch_sensor_values() is False
    assert sensors['2'].last_error == 'Abfrage fehlgeschlagen: HTTP 500 Internal Server Error'


def status_of(name):
    return next(t for t in thread_status.snapshot() if t['name'] == name)


def test_error_text_in_the_status_is_one_short_line():
    thread_status.register('SensorThread-2', 'Sensor 2', 7)
    run_in_thread('SensorThread-2', lambda: (thread_status.bind(), thread_status.report_error('Fehler: ' + HTML_PAGE)))
    text = status_of('SensorThread-2')['last_error']
    assert len(text) <= thread_status.MAX_ERROR_LENGTH and '\n' not in text


def test_event_log_records_start_reminder_and_end_of_an_outage_not_every_failure(monkeypatch):
    thread_status.register('SensorThread-2', 'Sensor 2', 7)

    def sequence():
        thread_status.bind()
        thread_status.report_success()
        for _ in range(3):
            thread_status.report_error('Abfrage fehlgeschlagen: HTTP 500')
        monkeypatch.setattr(thread_status, 'REMINDER_SECONDS', 0)
        thread_status.report_error('Abfrage fehlgeschlagen: HTTP 500')
        monkeypatch.setattr(thread_status, 'REMINDER_SECONDS', 3600)
        thread_status.report_error('Abfrage fehlgeschlagen: HTTP 500')
        thread_status.report_success()
        thread_status.report_success()
    run_in_thread('SensorThread-2', sequence)
    events = list(reversed(event_log.read_events(1)[0]))
    assert [e['kind'] for e in events] == ['error', 'ongoing', 'recovered']
    assert 'Wieder OK nach 5 Fehlversuch(en)' in events[2]['message']
    assert status_of('SensorThread-2')['error_count'] == 5, "the status still counts every failure"


def test_states_of_a_thread():
    import threading
    stop = threading.Event()
    thread_status.register('never', 'Nie gestartet', 60)
    thread_status.register('hanging', 'Hängt', 0.01)
    thread_status.register('crashed', 'Abgestürzt', 60)

    def hang():
        thread_status.bind()
        stop.wait()
    hanging = threading.Thread(target=hang, name='hanging', daemon=True)
    hanging.start()
    run_in_thread('crashed', lambda: (thread_status.bind(), thread_status.report_ended('ValueError: boom')))
    monkeypatch_limit = thread_status.STALE_MIN_SECONDS
    thread_status.STALE_MIN_SECONDS = 0.05
    try:
        time.sleep(0.2)
        assert status_of('never')['state'] == 'not_started'
        assert status_of('hanging')['state'] == 'stale'
        assert status_of('crashed')['state'] == 'stopped'
        assert status_of('crashed')['last_error'] == 'ValueError: boom'
    finally:
        thread_status.STALE_MIN_SECONDS = monkeypatch_limit
        stop.set()
        hanging.join()


def test_sensor_without_counting_is_idle_and_not_queried(sensors, monkeypatch):
    queried = []
    monkeypatch.setattr(sensors['10'], 'fetch_sensor_values', lambda: queried.append(1) or True)
    sensors['10'].counting = False
    thread_status.register('SensorThread-10', 'Sensor 10', 7)

    class Stop(BaseException):
        pass

    def one_cycle():
        thread_status.bind()
        monkeypatch.setattr(sensor_module.time, 'sleep', lambda seconds: (_ for _ in ()).throw(Stop()))
        with pytest.raises(Stop):
            sensor_module.sensor_thread(sensors['10'], 7)
        return status_of('SensorThread-10')  # read while the thread is alive, afterwards it counts as stopped
    status = run_in_thread('SensorThread-10', one_cycle)
    assert status['state'] == 'idle' and status['error_count'] == 0 and queried == []


def test_event_log_rotates_at_the_size_limit_and_reads_across_both_files():
    event_log.MAX_BYTES = 4000
    for index in range(60):
        event_log.event('error', f'SensorThread-{index % 3}', f'Eintrag {index} ' + 'x' * 80)
    sizes = {name: os.path.getsize(WORK / 'logs' / name) for name in sorted(os.listdir(WORK / 'logs'))}
    assert set(sizes) == {'events.log', 'events.log.1'}, "at most two files"
    assert all(size <= 4000 for size in sizes.values())
    events, truncated = event_log.read_events(None)
    assert events[0]['message'].startswith('Eintrag 59') and not truncated
    assert {e['source'] for e in event_log.read_events(None, 'SensorThread-1')[0]} == {'SensorThread-1'}
    assert event_log.read_events(None, None, limit=5) == (events[:5], True)


def test_events_are_filtered_by_time():
    import json
    old = {'ts': '2020-01-01 00:00:00', 'kind': 'error', 'source': 'X', 'label': 'X', 'message': 'alt'}
    with open(WORK / 'logs' / 'events.log', 'a', encoding='utf-8') as file:
        file.write(json.dumps(old) + '\n')
    event_log.event('error', 'X', 'neu')
    assert [e['message'] for e in event_log.read_events(1)[0]] == ['neu']
    assert [e['message'] for e in event_log.read_events(None)[0]] == ['neu', 'alt']


def detail_text(name):
    return (WORK / 'logs' / name).read_text(encoding='utf-8')


def test_detail_log_records_only_the_chosen_scope():
    name = event_log.start_detail(15, 'sensor:2')
    event_log.detail('SensorThread-2', 'GET https://x/getoutput | HTTP 200 | 12 ms')
    event_log.detail('SensorThread-3', 'fremder Sensor')
    event_log.detail('NavigatorUploadThread', 'Navigator')
    lines = [line for line in detail_text(name).splitlines() if not line.startswith('#')]
    assert len(lines) == 1 and 'SensorThread-2 | GET https://x/getoutput' in lines[0]


def test_detail_log_stops_when_the_time_is_over():
    name = event_log.start_detail(15, 'all')
    event_log._detail['until'] = time.time() - 1
    event_log.detail('SensorThread-2', 'nach Ablauf')
    status = event_log.detail_status()
    assert status['active'] is False and status['last_stop_reason'] == 'Zeit abgelaufen'
    assert 'nach Ablauf' not in detail_text(name)


def test_detail_log_stops_at_the_size_limit():
    event_log.MAX_BYTES = 600
    name = event_log.start_detail(60, 'all')
    for _ in range(30):
        event_log.detail('SensorThread-1', 'y' * 60)
    status = event_log.detail_status()
    assert status['active'] is False and status['last_stop_reason'] == 'Größenlimit erreicht'
    assert os.path.getsize(WORK / 'logs' / name) <= 600


def test_detail_log_files_cannot_be_used_to_reach_other_files():
    name = event_log.start_detail(15, 'all')
    assert event_log.detail_file_path('../config.json') is None
    assert event_log.detail_file_path('events.log') is None
    assert event_log.delete_detail_file(name) is False, "the file being written cannot be deleted"
    event_log.stop_detail()
    assert event_log.delete_detail_file(name) is True


def test_detail_log_through_the_api(admin):
    assert admin.post('/api/detail_log/start', json={'minutes': 7, 'scope': 'all'}).status_code == 400
    assert admin.post('/api/detail_log/start', json={'minutes': 15, 'scope': 'sensor:99'}).status_code == 400
    started = admin.post('/api/detail_log/start', json={'minutes': 15, 'scope': 'sensor:2'})
    assert started.status_code == 200
    name = started.get_json()['file']
    state = admin.get('/api/detail_log').get_json()
    assert state['active'] is True and state['scope'] == 'sensor:2' and state['max_bytes'] == 200 * 1024 * 1024
    assert admin.get(f'/api/detail_log/files/{name}').status_code == 200
    assert admin.delete(f'/api/detail_log/files/{name}').status_code == 400
    admin.post('/api/detail_log/stop')
    assert admin.delete(f'/api/detail_log/files/{name}').status_code == 200
    assert admin.get(f'/api/detail_log/files/{name}').status_code == 404


def test_requests_to_a_sensor_are_written_to_the_detail_log_without_the_login_answer(sensors, monkeypatch):
    import src.sensor_base as sensor_base

    class Reply:
        status_code, text = 200, '{"token": "GEHEIM"}'

    monkeypatch.setattr(sensor_base.requests.Session, 'request', lambda self, method, url, **kw: Reply())
    name = event_log.start_detail(15, 'sensor:2')
    sensors['2'].session.request('POST', 'https://192.0.2.2/webservice/login', json={'password': 'iee-alt'})
    sensors['2'].session.request('GET', 'https://192.0.2.2/webservice/getoutput')
    text = detail_text(name)
    assert 'GEHEIM' not in text.split('getoutput')[0], "the answer to a login is not written"
    assert 'iee-alt' not in text, "request bodies are never written"
    assert 'POST https://192.0.2.2/webservice/login | HTTP 200' in text and '(nicht protokolliert)' in text


def test_event_log_through_the_api(admin):
    event_log.event('error', 'SensorThread-2', 'Abfrage fehlgeschlagen: HTTP 500', 'Sensor 2')
    event_log.event('schedule', 'SchedulerThread', 'Zeitplan 1 (reset): alle 2 Sensoren erfolgreich', 'Scheduler')
    data = admin.get('/api/events?hours=1').get_json()
    assert [e['kind_label'] for e in data['events']] == ['Zeitplan', 'Fehler']
    assert len(admin.get('/api/events?hours=1&source=SensorThread-2').get_json()['events']) == 1
    export = admin.get('/api/events/export?hours=1').get_data(as_text=True)
    assert 'VIS Ereignisprotokoll' in export and 'Abfrage fehlgeschlagen: HTTP 500' in export


# ---- Fault indicator of the display ------------------------------------------

def fail_since(name, seconds):
    """Let a sensor thread fail and move the start of the failure into the past"""
    thread_status.register(name, name, 7)

    def body():
        thread_status.bind()
        thread_status.report_error('Abfrage fehlgeschlagen: Zeitüberschreitung')
    run_in_thread(name, body)
    thread_status._entries[name]['streak_started'] -= datetime.timedelta(seconds=seconds)
    # The helper thread has ended; a real sensor thread keeps running
    thread_status._entries[name]['thread'] = threading.current_thread()
    thread_status._entries[name]['ended'] = False


def faults(client):
    return {group['group_id']: group['fault'] for group in client.get('/api/get_data').get_json()['groups']}


def test_display_is_told_about_a_sensor_that_fails_for_a_while(anonymous):
    assert faults(anonymous) == {'1': False, '2': False, '3': False}
    fail_since('SensorThread-2', 60)       # sensor 2 belongs to group 1; one minute is not "for a while"
    assert faults(anonymous) == {'1': False, '2': False, '3': False}
    fail_since('SensorThread-2', 6 * 60)   # default limit: 5 minutes
    assert faults(anonymous) == {'1': True, '2': False, '3': False}


def test_fault_ends_with_the_first_successful_query(anonymous):
    fail_since('SensorThread-3', 3600)
    assert faults(anonymous)['2'] is True
    run_in_thread('SensorThread-3', thread_status.report_success)
    thread_status._entries['SensorThread-3']['thread'] = threading.current_thread()
    assert faults(anonymous)['2'] is False


def test_sensor_without_counting_causes_no_fault(admin, anonymous):
    fail_since('SensorThread-10', 3600)    # sensor 10 belongs to group 2
    assert faults(anonymous)['2'] is True
    assert admin.post('/api/sensors/10/edit', json={'counting': False}).status_code == 200
    assert faults(anonymous)['2'] is False


def test_ended_and_silent_threads_count_as_fault():
    thread_status.register('SensorThread-1', 'Sensor 1', 7)
    run_in_thread('SensorThread-1', lambda: (thread_status.bind(), thread_status.report_success()))
    entry = thread_status._entries['SensorThread-1']
    entry['last_run'] -= datetime.timedelta(seconds=900)
    assert thread_status.fault_seconds('SensorThread-1') >= 900, "the thread is not alive any more"
    entry['thread'] = threading.current_thread()
    assert thread_status.fault_seconds('SensorThread-1') >= 900, "alive, but no report for 15 minutes"
    entry['last_run'] = datetime.datetime.now()
    assert thread_status.fault_seconds('SensorThread-1') == 0
    assert thread_status.fault_seconds('SensorThread-99') == 0


def test_display_page_contains_the_hidden_fault_indicator(anonymous):
    page = anonymous.get('/visualize/display?group_id=1').get_data(as_text=True)
    assert 'id="fault-indicator"' in page and 'style="display: none;"' in page
