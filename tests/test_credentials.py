"""Sensor and Navigator credentials: lookup order and the pages that change them"""
import os

from dotenv import dotenv_values

from conftest import ENV_FILE, ROOT, client_for, flash_messages, read_config, write_config

import routes.admin as admin_routes
from src import sensor as sensor_module, sensor_credentials as credentials

IEE = {'sensor_id': '2', 'type': 'IEE', 'password': 'aus-config'}
KAM = {'sensor_id': '1', 'type': 'AI_HANWHA', 'username': 'u-config', 'password': 'p-config'}


def test_lookup_order_single_value_then_type_default_then_configuration():
    assert credentials.resolve_field(IEE, 'password', {}) == ('aus-config', 'config')
    assert credentials.resolve_field(IEE, 'password', {'SENSOR_IEE_PASSWORD': 'typ'}) == ('typ', 'type')
    env = {'SENSOR_IEE_PASSWORD': 'typ', 'SENSOR_2_PASSWORD': 'einzel'}
    assert credentials.resolve_field(IEE, 'password', env) == ('einzel', 'sensor')
    assert credentials.resolve_field({'sensor_id': '2', 'type': 'IEE'}, 'password', {}) == ('', 'missing')


def test_user_name_and_password_are_looked_up_independently():
    resolved = credentials.resolve(KAM, {'SENSOR_HANWHA_USERNAME': 'u-typ', 'SENSOR_1_PASSWORD': 'p-einzel'})
    assert resolved == {'username': ('u-typ', 'type'), 'password': ('p-einzel', 'sensor')}


def test_sensors_are_created_with_the_credentials_from_the_environment(monkeypatch):
    monkeypatch.setenv('SENSOR_IEE_PASSWORD', 'typ')
    monkeypatch.setenv('SENSOR_3_PASSWORD', 'einzel')
    loaded = {s.sensor_id: s for s in sensor_module.load_sensors_from_config('config.json')}
    assert (loaded['2'].password, loaded['3'].password, loaded['1'].password) == ('typ', 'einzel', 'kam-alt')


def test_migration_plan_uses_type_defaults_and_single_values_for_exceptions(config):
    config['sensors'][2]['password'] = 'iee-sonder'
    plan = credentials.plan_migration(config, {})
    assert plan == {'SENSOR_IEE_PASSWORD': 'iee-alt', 'SENSOR_3_PASSWORD': 'iee-sonder',
                    'SENSOR_HANWHA_USERNAME': 'admin', 'SENSOR_HANWHA_PASSWORD': 'kam-alt'}


def test_page_never_contains_passwords(admin):
    html = admin.get('/admin/sensor_credentials').get_data(as_text=True)
    assert html.count('config.json (alt)') == 4
    assert 'kam-alt' not in html and 'iee-alt' not in html


def test_takeover_moves_the_credentials_to_env_and_keeps_every_sensor_working(admin, sensors, config):
    config['sensors'][2]['password'] = 'iee-sonder'
    write_config(config)
    sensor_module.sensors[:] = sensor_module.load_sensors_from_config('config.json')
    before = read_config()
    response = admin.post('/admin/sensor_credentials', data={'action': 'migrate'}, follow_redirects=True)
    assert 'in die .env übernommen' in flash_messages(response)[0]
    stored = dotenv_values(ENV_FILE)
    assert stored == {'SENSOR_IEE_PASSWORD': 'iee-alt', 'SENSOR_3_PASSWORD': 'iee-sonder',
                      'SENSOR_HANWHA_USERNAME': 'admin', 'SENSOR_HANWHA_PASSWORD': 'kam-alt'}
    after = read_config()
    assert all('password' not in s and 'username' not in s for s in after['sensors'])
    strip = lambda entry: {k: v for k, v in entry.items() if k not in ('username', 'password')}
    assert [strip(s) for s in before['sensors']] == after['sensors']
    assert after['groups'] == before['groups'] and after['schedules'] == before['schedules']
    reloaded = {s.sensor_id: s for s in sensor_module.load_sensors_from_config('config.json')}  # like a restart
    assert (reloaded['2'].password, reloaded['3'].password) == ('iee-alt', 'iee-sonder')
    assert (reloaded['1'].username, reloaded['1'].password) == ('admin', 'kam-alt')
    assert 'config.json (alt)' not in admin.get('/admin/sensor_credentials').get_data(as_text=True)


def test_changes_apply_to_the_running_sensors_and_special_characters_survive(admin, sensors):
    password = 'Neu$"\' #1 \\ ä'
    form = {'action': 'save', 'type_HANWHA_username': '', 'type_IEE_password': password}
    assert 'gespeichert' in flash_messages(admin.post('/admin/sensor_credentials', data=form, follow_redirects=True))[0]
    assert dotenv_values(ENV_FILE)['SENSOR_IEE_PASSWORD'] == password
    assert sensors['2'].password == password and sensors['1'].password == 'kam-alt'


def test_single_value_overrides_the_type_default_and_can_be_removed(admin, sensors):
    base = {'action': 'save', 'type_HANWHA_username': 'admin'}
    admin.post('/admin/sensor_credentials', data={**base, 'type_HANWHA_password': 'typ-pw'})
    admin.post('/admin/sensor_credentials', data={**base, 'sensor_1_username': 'kamera1', 'sensor_1_password': 'einzel-pw'})
    assert (sensors['1'].username, sensors['1'].password) == ('kamera1', 'einzel-pw')
    assert (sensors['10'].username, sensors['10'].password) == ('admin', 'typ-pw')
    admin.post('/admin/sensor_credentials', data={**base, 'sensor_1_username': 'kamera1', 'sensor_1_clear': 'on'})
    assert (sensors['1'].username, sensors['1'].password) == ('admin', 'typ-pw')
    assert not [key for key in dotenv_values(ENV_FILE) if key.startswith('SENSOR_1_')]


def test_passwords_are_not_written_to_the_change_log(admin):
    admin.post('/admin/sensor_credentials', data={'action': 'save', 'type_HANWHA_username': 'admin', 'type_IEE_password': 'streng-geheim'})
    log = open('change_log.txt', encoding='utf-8').read()
    assert 'Sensor credentials changed' in log and 'streng-geheim' not in log


def test_only_administrators_can_change_credentials():
    for role in (None, 'Betrachter', 'Benutzer'):
        client = client_for(role)
        for path, form in (('/admin/sensor_credentials', {'action': 'save', 'type_IEE_password': 'fremd'}),
                           ('/admin/navigator', {'navigator_username': 'fremd', 'navigator_password': 'fremd'})):
            response = client.post(path, data=form)
            assert response.status_code == 302 and '/admin/login' in response.headers['Location'], (role, path)
    assert not ENV_FILE.exists() and os.environ['NAVIGATOR_USERNAME'] == 'nav-user'


def test_navigator_credentials_apply_without_restart_and_stay_hidden(admin):
    html = admin.get('/admin/navigator').get_data(as_text=True)
    assert 'value="nav-user"' in html and 'nav-pw' not in html
    response = admin.post('/admin/navigator', follow_redirects=True,
                          data={'navigator_username': 'neuer-user', 'navigator_password': 'neues-pw', 'action': 'save'})
    assert 'gespeichert' in flash_messages(response)[0] and 'neues-pw' not in response.get_data(as_text=True)
    assert (os.environ['NAVIGATOR_USERNAME'], os.environ['NAVIGATOR_PASSWORD']) == ('neuer-user', 'neues-pw')
    assert dotenv_values(ENV_FILE) == {'NAVIGATOR_USERNAME': 'neuer-user', 'NAVIGATOR_PASSWORD': 'neues-pw'}
    admin.post('/admin/navigator', data={'navigator_username': 'dritter', 'navigator_password': '', 'action': 'save'})
    assert os.environ['NAVIGATOR_PASSWORD'] == 'neues-pw', "an empty field keeps the stored password"


def test_navigator_connection_test_reports_the_result_without_showing_the_token(admin, monkeypatch):
    monkeypatch.setattr(admin_routes, 'create_OAUTH_token', lambda: 'GEHEIMES-TOKEN')
    form = {'navigator_username': 'nav-user', 'navigator_password': '', 'action': 'save_and_test'}
    response = admin.post('/admin/navigator', data=form, follow_redirects=True)
    assert any('Verbindungstest erfolgreich' in m for m in flash_messages(response))
    assert 'GEHEIMES-TOKEN' not in response.get_data(as_text=True)
    monkeypatch.setattr(admin_routes, 'create_OAUTH_token', lambda: False)
    response = admin.post('/admin/navigator', data=form, follow_redirects=True)
    assert any('Verbindungstest fehlgeschlagen' in m for m in flash_messages(response))


def test_tests_do_not_write_into_the_repository(admin):
    admin.post('/admin/navigator', data={'navigator_username': 'x', 'navigator_password': 'y', 'action': 'save'})
    assert ENV_FILE.exists()
    assert not (ROOT / '.env').exists() or 'NAVIGATOR_USERNAME=\'x\'' not in (ROOT / '.env').read_text()
