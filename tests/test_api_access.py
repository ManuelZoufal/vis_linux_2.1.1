"""Who may call which endpoint"""
import pytest

from conftest import client_for

JSON = {'Content-Type': 'application/json'}

# method, path, body - every endpoint that changes something or shows internal data
ADMIN_ONLY = [
    ('POST', '/api/sensors/2/reset', None),
    ('POST', '/api/sensors/2/reboot', None),
    ('POST', '/api/sensors/2/edit', {}),
    ('PUT', '/api/sensors/virtual/add', {'name': 'V', 'group_id': '1', 'occupancy': 0}),
    ('POST', '/api/sensors/virtual/99/edit', {}),
    ('DELETE', '/api/sensors/virtual/99/delete', None),
    ('PUT', '/api/groups/add', {'name': 'G', 'max_occupancy': 1}),
    ('POST', '/api/groups/1/edit', {}),
    ('DELETE', '/api/groups/3/delete', None),
    ('POST', '/api/groups/1/toggle_maintenance_mode', {'maintenance_mode': True}),
    ('POST', '/api/groups/1/update-settings', {}),
    ('GET', '/api/schedules', None),
    ('PUT', '/api/schedules/add', {'action': 'reset', 'interval': 'daily', 'time': '03:00', 'sensors': ['1']}),
    ('POST', '/api/schedules/1/edit', {}),
    ('DELETE', '/api/schedules/1/delete', None),
    ('GET', '/api/groups/1/display_images', None),
    ('DELETE', '/api/groups/1/display_images/0', None),
]
# endpoints that check the role themselves and answer 403 to everyone else
ADMIN_ONLY_403 = [
    ('GET', '/api/thread_status', None),
    ('GET', '/api/thread_status/export', None),
    ('GET', '/api/logs/export', None),
    ('GET', '/api/events', None),
    ('GET', '/api/events/export', None),
    ('GET', '/api/detail_log', None),
    ('POST', '/api/detail_log/start', {'minutes': 15, 'scope': 'all'}),
    ('POST', '/api/detail_log/stop', None),
    ('GET', '/api/detail_log/files/detail_20260101_000000.log', None),
    ('GET', '/api/server_log', None),
    ('POST', '/api/server_log/start', {'minutes': 15}),
    ('POST', '/api/server_log/stop', None),
]


def call(client, method, path, body):
    return client.open(path, method=method, json=body) if body is not None else client.open(path, method=method)


@pytest.mark.parametrize('method,path,body', ADMIN_ONLY)
def test_write_api_needs_a_login(method, path, body):
    assert call(client_for(None), method, path, body).status_code == 401


@pytest.mark.parametrize('method,path,body', ADMIN_ONLY)
@pytest.mark.parametrize('role', ['Benutzer', 'Betrachter'])
def test_write_api_needs_the_administrator_role(role, method, path, body):
    assert call(client_for(role), method, path, body).status_code == 403


@pytest.mark.parametrize('method,path,body', ADMIN_ONLY_403)
@pytest.mark.parametrize('role', [None, 'Benutzer', 'Betrachter'])
def test_internal_data_is_only_shown_to_administrators(role, method, path, body):
    assert call(client_for(role), method, path, body).status_code == 403


def test_api_answers_with_json_instead_of_a_redirect():
    response = client_for(None).post('/api/sensors/2/reset')
    assert response.status_code == 401
    assert response.get_json()['message'] == 'Anmeldung erforderlich'


def test_change_log_is_readable_for_every_logged_in_user():
    assert client_for(None).get('/api/logs').status_code == 401
    for role in ('Betrachter', 'Benutzer', 'Administrator'):
        assert client_for(role).get('/api/logs').status_code == 200


def test_visualization_settings_are_for_administrators_and_users():
    for role, expected in ((None, 302), ('Betrachter', 302), ('Benutzer', 200), ('Administrator', 200)):
        client = client_for(role)
        assert client.get('/visualize/configure').status_code == expected, role
        assert client.post('/visualize/update_marquee', data={'marquee_text': 'x'}).status_code == expected, role


def test_removed_endpoints_stay_removed(admin):
    for path in ('/api/debug_info', '/api/debug_info/export', '/api/sensors/2/webinterface/'):
        assert admin.get(path).status_code == 404, path


def test_get_data_is_public_but_contains_no_credentials(anonymous):
    data = anonymous.get('/api/get_data').get_json()
    assert len(data['sensors']) == 4
    for entry in data['sensors']:
        assert 'password' not in entry and 'username' not in entry
