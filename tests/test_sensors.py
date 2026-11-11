"""Sensors: editing, the counting switch, virtual sensors, reset and reboot"""
from conftest import read_config, write_config

from src import sensor as sensor_module
from src.database import get_connection, save_sensor_values


def sensor_config(sensor_id):
    return next(s for s in read_config()['sensors'] if s['sensor_id'] == sensor_id)


def database_ids():
    conn = get_connection()
    ids = [row[0] for row in conn.execute('SELECT sensor_id FROM sensor_data ORDER BY sensor_id')]
    conn.close()
    return ids


def test_edit_validates_and_leaves_the_running_sensor_untouched_on_error(admin, sensors):
    assert admin.post('/api/sensors/2/edit', json={'name': ''}).status_code == 400
    assert admin.post('/api/sensors/2/edit', json={'group_id': '99'}).status_code == 400
    assert admin.post('/api/sensors/2/edit', json={'counting': 'nein'}).status_code == 400
    assert sensors['2'].name == 'IEE2 | Eingang' and sensors['2'].group_id == '1'
    assert admin.post('/api/sensors/99/edit', json={'name': 'x'}).status_code == 404


def test_edit_changes_configuration_and_running_sensor(admin, sensors):
    response = admin.post('/api/sensors/2/edit', json={'name': 'Neu', 'group_id': '2', 'datapoint_id': '2002'})
    assert response.status_code == 200
    assert {k: sensor_config('2')[k] for k in ('name', 'group_id', 'datapoint_id')} == {'name': 'Neu', 'group_id': '2', 'datapoint_id': '2002'}
    assert (sensors['2'].name, sensors['2'].group_id, sensors['2'].datapoint_id) == ('Neu', '2', '2002')


def test_datapoint_is_shown_from_the_configuration_before_the_first_query(admin):
    """A sensor that was never reached has no database row. Its datapoint used to be shown as
    "N/A", and saving the edit dialog then wrote "N/A" over the configured datapoint."""
    shown = next(s for s in admin.get('/api/get_data').get_json()['sensors'] if s['sensor_id'] == '2')
    assert shown['datapoint_id'] == '1002'
    form = {k: shown[k] for k in ('sensor_id', 'name', 'ip_address', 'group_id', 'occupancy', 'datapoint_id', 'type')}
    assert admin.post('/api/sensors/2/edit', json=form).status_code == 200
    assert sensor_config('2')['datapoint_id'] == '1002'


def test_not_available_placeholder_is_stored_as_empty_datapoint(admin):
    assert admin.post('/api/sensors/2/edit', json={'datapoint_id': 'N/A'}).status_code == 200
    assert sensor_config('2')['datapoint_id'] == ''


def test_switching_counting_off_removes_the_sensor_from_occupancy(admin, sensors):
    sensors['1'].occupancy, sensors['2'].occupancy = 25, 18
    save_sensor_values(sensors['1'])
    save_sensor_values(sensors['2'])
    assert admin.get('/groups/1').get_json()['total_occupancy'] == 43
    assert admin.post('/api/sensors/1/edit', json={'counting': False}).status_code == 200
    assert sensors['1'].counting is False and sensor_config('1')['counting'] is False
    assert database_ids() == ['2']
    assert admin.get('/groups/1').get_json()['total_occupancy'] == 18
    shown = next(s for s in admin.get('/api/get_data').get_json()['sensors'] if s['sensor_id'] == '1')
    assert shown['counting'] is False and shown['occupancy'] == 0


def test_sensor_without_counting_cannot_be_reset_but_rebooted(admin, sensors, monkeypatch):
    admin.post('/api/sensors/1/edit', json={'counting': False})
    monkeypatch.setattr(sensors['1'], 'reboot_sensor', lambda: True)
    response = admin.post('/api/sensors/1/reset')
    assert response.status_code == 400
    assert 'nicht für die Zählung' in response.get_json()['message']
    assert admin.post('/api/sensors/1/reboot').status_code == 200


def test_counting_switch_is_read_from_the_configuration_at_start(config):
    config['sensors'][3]['counting'] = False
    write_config(config)
    loaded = {s.sensor_id: s for s in sensor_module.load_sensors_from_config('config.json')}
    assert loaded['10'].counting is False and loaded['1'].counting is True


def test_reset_and_reboot_report_failure_instead_of_always_success(admin, sensors, monkeypatch):
    """The buttons used to report success whatever the sensor answered."""
    def failing():
        sensors['2'].last_action_error = 'Anmeldung fehlgeschlagen: HTTP 401 Unauthorized'
        return False
    monkeypatch.setattr(sensors['2'], 'reset_sensor_values', failing)
    monkeypatch.setattr(sensors['2'], 'reboot_sensor', failing)
    for action in ('reset', 'reboot'):
        response = admin.post(f'/api/sensors/2/{action}')
        assert response.status_code == 502, action
        assert response.get_json()['message'] == 'Anmeldung fehlgeschlagen: HTTP 401 Unauthorized'
    monkeypatch.setattr(sensors['2'], 'reset_sensor_values', lambda: True)
    assert admin.post('/api/sensors/2/reset').status_code == 200
    assert admin.post('/api/sensors/99/reset').status_code == 404


def test_virtual_sensor_lifecycle(admin):
    assert admin.put('/api/sensors/virtual/add', json={'name': '', 'group_id': '1', 'occupancy': 1}).status_code == 400
    assert admin.put('/api/sensors/virtual/add', json={'name': 'V', 'group_id': '1', 'occupancy': 'abc'}).status_code == 400
    assert admin.put('/api/sensors/virtual/add', json={'name': 'V', 'group_id': '99', 'occupancy': 1}).status_code == 400
    created = admin.put('/api/sensors/virtual/add', json={'name': 'Terrasse', 'group_id': '1', 'occupancy': '5'}).get_json()['sensor']
    assert created == {'sensor_id': '11', 'type': 'VIRTUAL', 'name': 'Terrasse', 'group_id': '1', 'occupancy': 5}
    assert admin.post('/api/sensors/virtual/11/edit', json={'occupancy': '7'}).status_code == 200
    assert sensor_config('11')['occupancy'] == 7, "stored as a number, the display adds the values up"
    assert admin.post('/api/sensors/virtual/2/edit', json={'occupancy': 1}).status_code == 404, "not a virtual sensor"
    assert admin.delete('/api/sensors/virtual/11/delete').status_code == 200
    assert all(s['type'] != 'VIRTUAL' for s in read_config()['sensors'])


def test_virtual_sensors_are_skipped_when_the_sensors_are_loaded(config, caplog):
    """A virtual sensor in the configuration used to break the next start or duplicate another sensor."""
    config['sensors'].insert(0, {'sensor_id': '50', 'type': 'VIRTUAL', 'name': 'V', 'group_id': '1', 'occupancy': 3})
    config['sensors'].append({'sensor_id': '51', 'type': 'UNBEKANNT', 'name': 'X', 'group_id': '1'})
    write_config(config)
    with caplog.at_level('ERROR'):
        loaded = sensor_module.load_sensors_from_config('config.json')
    assert [s.sensor_id for s in loaded] == ['1', '2', '3', '10']
    complaints = [record.getMessage() for record in caplog.records if 'unknown type' in record.getMessage()]
    assert len(complaints) == 1 and 'Sensor 51' in complaints[0], "a virtual sensor is expected, only the unknown type is an error"


def test_api_and_scheduler_use_the_same_sensor_objects():
    """Two separate lists once made edits and scheduled uploads work on stale objects."""
    import routes.admin
    import routes.api
    import src.scheduler
    assert routes.api.sensors is sensor_module.sensors
    assert src.scheduler.sensors is sensor_module.sensors
    assert routes.admin.sensor_objects is sensor_module.sensors
