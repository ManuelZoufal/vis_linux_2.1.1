"""Change log, thread status export, verbose server log, certificate and timestamps"""
import logging
import os
import time
from datetime import datetime, timezone

from conftest import ROOT, WORK, client_for, run_in_thread

import routes.api as api
from src import certificate, event_log, helpers, server_log, thread_status


def test_change_log_shows_the_newest_entries_first_and_at_most_500(admin):
    for index in range(1200):
        helpers.log_change(f'Eintrag {index}')
    data = admin.get('/api/logs').get_json()
    assert len(data['logs']) == 500 and data['truncated'] is True
    assert data['logs'][0]['message'] == 'Eintrag 1199' and data['logs'][-1]['message'] == 'Eintrag 700'
    assert len(admin.get('/api/logs?limit=5000').get_json()['logs']) == 1200
    assert len(admin.get('/api/logs/export').get_data(as_text=True).splitlines()) == 1200


def test_damaged_lines_in_the_change_log_are_skipped(admin):
    helpers.log_change('vorher')
    with open('change_log.txt', 'a', encoding='utf-8') as file:
        file.write('Zeile ohne Trenner\n\n')
    helpers.log_change('nachher')
    assert [entry['message'] for entry in admin.get('/api/logs').get_json()['logs']] == ['nachher', 'vorher']


def test_missing_change_log_is_an_empty_log(admin):
    assert not os.path.exists('change_log.txt')
    assert admin.get('/api/logs').get_json()['logs'] == []


def test_change_log_rotates_at_the_size_limit():
    event_log.MAX_BYTES = 3000
    for index in range(120):
        helpers.log_change(f'Rotationstest {index} ' + 'y' * 40)
    sizes = {name: os.path.getsize(WORK / name) for name in os.listdir(WORK) if name.startswith('change_log')}
    assert set(sizes) == {'change_log.txt', 'change_log.txt.1'} and all(size <= 3000 for size in sizes.values())


def test_thread_status_export_lists_every_thread_with_a_short_error(admin):
    thread_status.register('SensorThread-2', 'Sensor 2: IEE2', 7)
    thread_status.register('SensorThread-10', 'Sensor 10: KAM10', 7)
    run_in_thread('SensorThread-2', lambda: (thread_status.bind(), thread_status.report_error('Abfrage fehlgeschlagen: HTTP 500 Internal Server Error')))
    text = admin.get('/api/thread_status/export').get_data(as_text=True)
    assert 'VIS Thread-Status' in text and 'Version:   ' in text
    assert 'Sensor 2: IEE2' in text and 'Abfrage fehlgeschlagen: HTTP 500 Internal Server Error' in text
    assert 'Sensor 10: KAM10' in text
    assert len(text.splitlines()) < 30


def test_thread_status_counts_sensors_without_counting_separately(admin):
    thread_status.register('SensorThread-1', 'Sensor 1', 7)
    thread_status.register('SensorThread-10', 'Sensor 10', 7)
    import threading
    stop = threading.Event()
    started = threading.Barrier(3)

    def worker(report):
        thread_status.bind()
        report()
        started.wait()
        stop.wait()
    threads = [threading.Thread(target=worker, args=(thread_status.report_success,), name='SensorThread-1', daemon=True),
               threading.Thread(target=worker, args=(lambda: thread_status.report_idle('Keine Zählung'),), name='SensorThread-10', daemon=True)]
    for thread in threads:
        thread.start()
    started.wait()
    try:
        states = {t['name']: t['state'] for t in admin.get('/api/thread_status').get_json()['threads']}
        assert states == {'SensorThread-1': 'ok', 'SensorThread-10': 'idle'}
        assert 'Übersicht: 1 von 1 Threads OK, 1 ohne Zählung' in admin.get('/api/thread_status/export').get_data(as_text=True)
    finally:
        stop.set()
        for thread in threads:
            thread.join()


def levels():
    return logging.getLogger().level, logging.getLogger('werkzeug').level


def test_verbose_server_log_changes_only_the_log_levels_and_switches_itself_off():
    logging.getLogger().setLevel(logging.INFO)
    logging.getLogger('werkzeug').setLevel(logging.WARNING)
    server_log.init(False)
    try:
        server_log.start(0.3)
        assert levels() == (logging.DEBUG, logging.INFO) and server_log.status()['active'] is True
        time.sleep(0.6)
        assert levels() == (logging.INFO, logging.WARNING)
        status = server_log.status()
        assert status['active'] is False and status['last_stop_reason'] == 'Zeit abgelaufen'
        server_log.start(60)
        assert server_log.stop() is True and levels() == (logging.INFO, logging.WARNING)
    finally:
        server_log.stop()


def test_verbose_server_log_through_the_api_never_enables_the_debugger(admin):
    from conftest import flask_app
    assert admin.post('/api/server_log/start', json={'minutes': 99999}).status_code == 400
    assert admin.post('/api/server_log/start', json={'minutes': 15}).status_code == 200
    assert admin.get('/api/server_log').get_json()['active'] is True
    assert flask_app.debug is False, "the Werkzeug debugger stays bound to APP_DEBUG"
    assert admin.get('/console').status_code == 404
    assert admin.post('/api/server_log/stop').get_json()['stopped'] is True
    assert 'Verbose server log switched on' in open('change_log.txt', encoding='utf-8').read()


def test_certificate_states(monkeypatch):
    now = time.time()
    monkeypatch.setattr(certificate.os.path, 'getmtime', lambda path: 1.0)
    certificate._loaded.update(not_after=now + 200 * 86400, mtime=1.0)
    assert certificate.get_status()['state'] == 'ok'
    certificate._loaded['not_after'] = now + 10 * 86400
    status = certificate.get_status()
    assert status['state'] == 'warning' and 'noch 9 Tage' in status['message'] or 'noch 10 Tage' in status['message']
    certificate._loaded['not_after'] = now - 3 * 86400
    assert certificate.get_status()['state'] == 'expired'
    certificate._loaded.update(not_after=now + 200 * 86400, mtime=2.0)
    assert certificate.get_status()['restart_needed'] is True
    certificate._loaded['not_after'] = None
    assert certificate.get_status()['state'] == 'unknown'


def test_certificate_banner_is_only_shown_to_administrators(admin, anonymous, monkeypatch):
    monkeypatch.setattr(certificate.os.path, 'getmtime', lambda path: 1.0)
    certificate._loaded.update(not_after=time.time() + 5 * 86400, mtime=1.0)
    assert 'certificate-banner' in admin.get('/general_overview').get_data(as_text=True)
    assert 'certificate-banner' not in anonymous.get('/general_overview').get_data(as_text=True)
    assert 'certificate' not in anonymous.get('/api/get_data').get_json()


def test_timestamps_follow_daylight_saving_time():
    """A fixed offset of one hour was wrong for half of the year."""
    assert str(api.DISPLAY_TIMEZONE) == 'Europe/Berlin'
    convert = lambda text: datetime.strptime(text, '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc).astimezone(api.DISPLAY_TIMEZONE).strftime('%H:%M %Z')
    assert convert('2026-11-10 10:00:00') == '11:00 CET'
    assert convert('2027-07-01 10:00:00') == '12:00 CEST'


# ---- Layout of the logs page and the settings page ---------------------------

def test_logs_page_has_tabs_and_pages_for_administrators(admin):
    page = admin.get('/logs').get_data(as_text=True)
    for tab in ('status', 'events', 'changes', 'detail'):
        assert f'data-tab="{tab}"' in page and f'id="tab-{tab}"' in page
    assert 'id="logs-pager"' in page and 'id="event-pager"' in page and 'js/pager.js' in page
    # Certificate and verbose server log moved to the settings page
    assert 'certificate-renew-button' not in page and 'server-log-minutes' not in page


def test_other_users_only_see_the_change_log():
    page = client_for('Betrachter').get('/logs').get_data(as_text=True)
    assert 'id="tab-changes"' in page and 'id="logs-pager"' in page
    assert 'id="log-tabs"' not in page and 'id="tab-status"' not in page and 'id="tab-detail"' not in page


def test_settings_page_is_for_administrators(admin, anonymous):
    assert anonymous.get('/settings').status_code == 302
    assert client_for('Benutzer').get('/settings').status_code in (302, 403)
    page = admin.get('/settings').get_data(as_text=True)
    for expected in ('certificate-renew-button', 'server-log-minutes', '/admin/navigator', '/admin/sensor_credentials', 'js/settings.js'):
        assert expected in page
    navigation = admin.get('/logs').get_data(as_text=True).split('class="container"')[0]
    assert 'href="/settings"' in navigation and '/admin/navigator' not in navigation


def test_pager_shows_twenty_rows_per_page():
    """The page size is part of the script; the behaviour itself is checked in the browser."""
    script = (ROOT / 'static/js/pager.js').read_text(encoding='utf-8')
    assert 'const PAGE_SIZE = 20;' in script
