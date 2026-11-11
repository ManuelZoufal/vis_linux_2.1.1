"""Groups: validation, storage and deletion"""
import os

import pytest

from conftest import WORK, read_config, write_config

import routes.api as api


def group(group_id):
    return next(g for g in read_config()['groups'] if g['group_id'] == group_id)


@pytest.mark.parametrize('body,message', [
    ({'max_occupancy': 10}, 'Der Name darf nicht leer sein'),
    ({'name': '   ', 'max_occupancy': 10}, 'Der Name darf nicht leer sein'),
    ({'name': 'G', 'max_occupancy': 'abc'}, 'Die maximale Belegung muss eine ganze Zahl sein'),
    ({'name': 'G'}, 'Die maximale Belegung muss eine ganze Zahl sein'),
    ({'name': 'G', 'max_occupancy': -5}, 'Die maximale Belegung darf nicht negativ sein'),
    ({'name': 'G', 'max_occupancy': 5, 'maintenance_mode': 'ja'}, 'Der Wartungsmodus muss true oder false sein'),
])
def test_invalid_group_is_rejected_and_nothing_is_written(admin, body, message):
    before = read_config()
    response = admin.put('/api/groups/add', json=body)
    assert response.status_code == 400
    assert response.get_json()['message'] == message
    assert read_config() == before


def test_request_without_json_is_rejected_instead_of_crashing(admin):
    assert admin.put('/api/groups/add', data='kein json').status_code == 400


def test_new_group_gets_the_next_id_and_a_numeric_maximum(admin):
    response = admin.put('/api/groups/add', json={'name': ' Terrasse ', 'max_occupancy': '80', 'welcome_text': 'Hallo'})
    assert response.status_code == 200
    created = response.get_json()['group']
    assert created['group_id'] == '4' and created['name'] == 'Terrasse'
    assert group('4')['max_occupancy'] == 80


def test_partial_edit_keeps_the_other_fields_and_converts_the_maximum(admin):
    assert group('1')['max_occupancy'] == '150', "the starting configuration stores it as text"
    assert admin.post('/api/groups/1/edit', json={'welcome_text': 'Neu'}).status_code == 200
    edited = group('1')
    assert edited['welcome_text'] == 'Neu' and edited['name'] == 'Gruppe Eins'
    assert edited['max_occupancy'] == 150
    assert 'display_images' in edited


def test_update_settings_works_and_validates(admin):
    assert admin.post('/api/groups/1/update-settings', json={'name': 'Umbenannt'}).status_code == 200
    assert group('1')['name'] == 'Umbenannt'
    assert admin.post('/api/groups/1/update-settings', json={'max_occupancy': 'x'}).status_code == 400


def test_maintenance_switch_needs_a_boolean(admin):
    assert admin.post('/api/groups/1/toggle_maintenance_mode', json={'maintenance_mode': 'true'}).status_code == 400
    assert admin.post('/api/groups/1/toggle_maintenance_mode', json={'maintenance_mode': True}).status_code == 200
    assert group('1')['maintenance_mode'] is True


def test_unknown_group_gives_404(admin):
    assert admin.post('/api/groups/99/edit', json={'name': 'x'}).status_code == 404
    assert admin.delete('/api/groups/99/delete').status_code == 404


def test_deleting_a_group_moves_its_sensors_to_one_default_group(admin, sensors):
    assert admin.delete('/api/groups/1/delete').status_code == 200
    config = read_config()
    assert [g['group_id'] for g in config['groups']] == ['2', '3', '0']
    assert [s['group_id'] for s in config['sensors']] == ['0', '0', '2', '2'], "group ids stay text"
    assert sensors['1'].group_id == '0' and sensors['2'].group_id == '0', "the running sensor objects follow"
    assert admin.delete('/api/groups/2/delete').status_code == 200
    assert [g['group_id'] for g in read_config()['groups']] == ['3', '0'], "the default group is created only once"


def test_default_group_cannot_be_deleted_while_it_has_sensors(admin):
    admin.delete('/api/groups/1/delete')
    response = admin.delete('/api/groups/0/delete')
    assert response.status_code == 400
    assert 'Standardgruppe' in response.get_json()['message']


def test_deleting_a_group_removes_its_images_and_nothing_else(admin, monkeypatch, config):
    uploads = WORK / 'uploads-test'
    uploads.mkdir(exist_ok=True)
    monkeypatch.setattr(api, '_upload_folder', lambda: str(uploads))
    for name in ('group_3_img_0.png', 'group_3_img_2.jpg', 'andere.png'):
        (uploads / name).write_bytes(b'x')
    config['groups'][2]['display_images'] = ['group_3_img_0.png', None, 'group_3_img_2.jpg', '../config.json']
    write_config(config)
    assert admin.delete('/api/groups/3/delete').status_code == 200
    assert sorted(os.listdir(uploads)) == ['andere.png']
    assert (WORK / 'config.json').exists(), "a path outside the upload folder must never be deleted"


def test_group_occupancy_adds_up_database_and_virtual_sensors(admin, sensors):
    from src.database import save_sensor_values
    sensors['1'].occupancy, sensors['2'].occupancy = 25, 18
    save_sensor_values(sensors['1'])
    save_sensor_values(sensors['2'])
    admin.put('/api/sensors/virtual/add', json={'name': 'Terrasse', 'group_id': '1', 'occupancy': 7})
    assert admin.get('/groups/1').get_json()['total_occupancy'] == 50
