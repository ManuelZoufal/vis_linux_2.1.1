"""Schedules: API, jobs in the schedule library and execution"""
import datetime

import pytest
import schedule as schedule_lib

from conftest import read_config, run_in_thread

from src import event_log, scheduler, thread_status


@pytest.fixture
def loaded_jobs():
    """What the scheduler thread does at start: plan the schedules of the configuration"""
    for entry in scheduler.load_schedule_from_config('config.json'):
        scheduler.schedule_job(entry)


def job_for(schedule_id):
    return [job for job in schedule_lib.jobs if scheduler.schedule_tag(schedule_id) in job.tags]


def test_editing_changes_the_existing_schedule_and_its_job(admin, loaded_jobs):
    """Editing used to answer 404 (id compared as text with number) and never reached the running job."""
    response = admin.post('/api/schedules/1/edit', json={'time': '06:30'})
    assert response.status_code == 200
    assert read_config()['schedules'][0]['time'] == '06:30'
    assert len(schedule_lib.jobs) == 1
    assert str(job_for(1)[0].at_time) == '06:30:00'


def test_adding_and_deleting_takes_effect_in_the_running_scheduler(admin, loaded_jobs):
    body = {'action': 'reboot', 'interval': 'weekly', 'day': 'sunday', 'time': '04:00', 'sensors': ['1', '2']}
    created = admin.put('/api/schedules/add', json=body).get_json()['schedule']
    assert created['id'] == 2
    job = job_for(2)[0]
    assert (job.unit, job.start_day, str(job.at_time)) == ('weeks', 'sunday', '04:00:00')
    assert admin.delete('/api/schedules/2/delete').status_code == 200
    assert job_for(2) == [] and len(read_config()['schedules']) == 1
    assert admin.delete('/api/schedules/2/delete').status_code == 404


@pytest.mark.parametrize('body,fragment', [
    ({'action': 'reset', 'interval': 'daily', 'time': '25:00', 'sensors': ['1']}, 'Ungültige Uhrzeit'),
    ({'action': 'format', 'interval': 'daily', 'time': '03:00', 'sensors': ['1']}, 'Unbekannte Aktion'),
    ({'action': 'reset', 'interval': 'manchmal', 'time': '03:00', 'sensors': ['1']}, 'Unbekanntes Intervall'),
    ({'action': 'reset', 'interval': 'daily', 'time': '03:00', 'sensors': []}, 'mindestens ein Sensor'),
    ({'action': 'reset', 'interval': 'daily', 'time': '03:00', 'sensors': ['99']}, 'Unbekannte Sensoren'),
    ({'action': 'reset', 'interval': 'weekly', 'day': '', 'time': '03:00', 'sensors': ['1']}, 'Ungültiger Wochentag'),
])
def test_invalid_schedule_is_rejected_before_anything_is_written(admin, loaded_jobs, body, fragment):
    before = read_config()
    response = admin.put('/api/schedules/add', json=body)
    assert response.status_code == 400 and fragment in response.get_json()['message']
    assert read_config() == before and len(schedule_lib.jobs) == 1
    assert admin.post('/api/schedules/1/edit', json={'time': '99:99'}).status_code == 400


def test_every_interval_can_be_scheduled():
    for index, interval in enumerate(scheduler.INTERVALS):
        entry = {'id': 100 + index, 'action': 'reset', 'interval': interval, 'day': 'Monday', 'time': '03:00', 'sensors': ['1']}
        assert scheduler.validate_schedule(entry) is None, interval
        scheduler.schedule_job(entry)
    assert len(schedule_lib.jobs) == len(scheduler.INTERVALS)


class FakeSensor:
    def __init__(self, sensor_id, mode='ok', counting=True):
        self.sensor_id, self.name, self.mode, self.counting = sensor_id, f'S{sensor_id}', mode, counting
        self.last_action_error, self.datapoint_id, self.occupancy = None, '1', 1
        self.calls = []

    def _act(self, what):
        self.calls.append(what)
        self.last_action_error = None
        if self.mode == 'boom':
            raise RuntimeError('kaputt')
        if self.mode == 'fail':
            self.last_action_error = f'{what} fehlgeschlagen: Zeitüberschreitung beim Verbindungsaufbau'
            return False
        return True

    def reset_sensor_values(self):
        return self._act('Zurücksetzen')

    def reboot_sensor(self):
        return self._act('Neustart')


def execute(monkeypatch, fakes, schedule):
    monkeypatch.setattr(scheduler, 'sensors', fakes)
    thread_status.register('SchedulerThread', 'Scheduler', 1)

    def body():
        thread_status.bind()
        scheduler.execute_schedule(schedule)
    run_in_thread('SchedulerThread', body)
    return next(t for t in thread_status.snapshot() if t['name'] == 'SchedulerThread')


def test_one_failing_sensor_does_not_stop_the_others_and_the_reason_is_reported(monkeypatch):
    fakes = [FakeSensor('1'), FakeSensor('2', 'fail'), FakeSensor('3', 'boom'), FakeSensor('4')]
    status = execute(monkeypatch, fakes, {'id': 1, 'action': 'reset', 'sensors': ['1', '2', '3', '4']})
    assert [f.calls for f in fakes] == [['Zurücksetzen']] * 4, "every sensor is tried exactly once"
    assert status['last_error'].startswith('Zeitplan 1 (reset): 2 von 4 fehlgeschlagen')
    assert 'S2: Zurücksetzen fehlgeschlagen: Zeitüberschreitung beim Verbindungsaufbau' in status['last_error']
    assert 'S3: RuntimeError: kaputt' in status['last_error']
    events = [e for e in event_log.read_events(1)[0] if e['kind'] == 'schedule']
    assert len(events) == 1 and '2 von 4 fehlgeschlagen' in events[0]['message']


def test_a_failing_job_is_not_repeated_every_second(monkeypatch):
    """The schedule library plans the next run only after the job returned.
    A job that raises would therefore run again with every check."""
    fake = FakeSensor('1', 'boom')
    monkeypatch.setattr(scheduler, 'sensors', [fake])
    scheduler.schedule_job({'id': 5, 'action': 'reset', 'interval': 'daily', 'day': '', 'time': '03:00', 'sensors': ['1']})
    schedule_lib.jobs[0].next_run = datetime.datetime.now() - datetime.timedelta(seconds=1)
    for _ in range(3):
        schedule_lib.run_pending()
    assert fake.calls == ['Zurücksetzen']


def test_sensors_without_counting_are_skipped_by_reset_and_upload_but_rebooted(monkeypatch):
    uploads = []
    monkeypatch.setattr(scheduler, 'upload_data_to_navigator', lambda datapoint, occupancy, name: uploads.append(name) or True)
    fakes = [FakeSensor('8'), FakeSensor('9', counting=False), FakeSensor('10', 'fail', counting=False)]
    ids = ['8', '9', '10']
    status = execute(monkeypatch, fakes, {'id': 1, 'action': 'reset', 'sensors': ids})
    assert [f.calls for f in fakes] == [['Zurücksetzen'], [], []]
    assert status['error_count'] == 0, "a skipped sensor is not a failure"
    execute(monkeypatch, fakes, {'id': 7, 'action': 'upload', 'sensors': ids})
    assert uploads == ['S8']
    execute(monkeypatch, fakes, {'id': 3, 'action': 'reboot', 'sensors': ids})
    assert [f.calls[-1] for f in fakes] == ['Neustart'] * 3, "a reboot stays possible without counting"
    messages = [e['message'] for e in event_log.read_events(1)[0] if e['kind'] == 'schedule']
    assert any('2 ohne Zählung übersprungen' in m for m in messages)


def test_description_is_stored_shown_and_can_be_changed(admin, loaded_jobs):
    body = {'action': 'reset', 'interval': 'daily', 'time': '03:00', 'sensors': ['1'], 'description': '  Nachtreset Eingang  '}
    created = admin.put('/api/schedules/add', json=body).get_json()['schedule']
    assert created['description'] == 'Nachtreset Eingang'
    assert read_config()['schedules'][1]['description'] == 'Nachtreset Eingang'
    assert admin.post('/api/schedules/2/edit', json={'description': 'Neu'}).status_code == 200
    assert read_config()['schedules'][1]['description'] == 'Neu'
    # Editing another field keeps the description; an empty one removes the text
    assert admin.post('/api/schedules/2/edit', json={'time': '04:00'}).status_code == 200
    assert read_config()['schedules'][1]['description'] == 'Neu'
    assert admin.post('/api/schedules/2/edit', json={'description': ''}).status_code == 200
    assert read_config()['schedules'][1].get('description', '') == ''
    # Schedules from before this field have none and stay valid
    assert 'description' not in read_config()['schedules'][0]
    assert admin.post('/api/schedules/1/edit', json={'time': '06:30'}).status_code == 200


@pytest.mark.parametrize('description,fragment', [('x' * 101, 'höchstens 100'), (5, 'Text')])
def test_invalid_description_is_rejected(admin, loaded_jobs, description, fragment):
    before = read_config()
    body = {'action': 'reset', 'interval': 'daily', 'time': '03:00', 'sensors': ['1'], 'description': description}
    response = admin.put('/api/schedules/add', json=body)
    assert response.status_code == 400 and fragment in response.get_json()['message']
    assert read_config() == before
    assert admin.put('/api/schedules/add', json={**body, 'description': 'x' * 100}).status_code == 200


def test_description_appears_in_the_report_of_an_executed_schedule(monkeypatch):
    execute(monkeypatch, [FakeSensor('1')], {'id': 7, 'action': 'reset', 'sensors': ['1'], 'description': 'Nachtreset'})
    events = [e for e in event_log.read_events(1)[0] if e['kind'] == 'schedule']
    assert len(events) == 1 and events[0]['message'].startswith('Zeitplan 7 „Nachtreset“ (reset)')
    status = execute(monkeypatch, [FakeSensor('1', 'fail')], {'id': 8, 'action': 'reset', 'sensors': ['1']})
    assert status['last_error'].startswith('Zeitplan 8 (reset)')

