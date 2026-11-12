"""Login, lockout, roles and user management"""
from conftest import client_for, create_user, flash_messages, login, new_client, read_config

from src import login_guard
from src.database import get_connection


def test_login_with_correct_and_wrong_password():
    assert login(new_client(), 'admin', 'admin-pw')
    response = new_client().post('/admin/login', data={'username': 'admin', 'password': 'falsch'})
    assert response.status_code == 200
    assert 'Benutzername oder Passwort falsch!' in flash_messages(response)


def test_pages_redirect_to_login_without_session(anonymous):
    for path in ('/admin/', '/sensor_settings', '/group_settings', '/schedules', '/logs', '/admin/users',
                 '/admin/navigator', '/admin/sensor_credentials', '/visualize/configure'):
        response = anonymous.get(path)
        assert response.status_code == 302, path
        assert '/admin/login' in response.headers['Location'], path


def test_public_pages_work_without_login(anonymous):
    for path in ('/', '/general_overview', '/visualize/', '/visualize/display?group_id=1', '/api/get_data', '/groups/1'):
        assert anonymous.get(path).status_code == 200, path


def test_login_is_locked_after_repeated_failures_even_with_correct_password():
    for _ in range(login_guard.MAX_ATTEMPTS):
        assert new_client().post('/admin/login', data={'username': 'admin', 'password': 'x'}).status_code == 200
    response = new_client().post('/admin/login', data={'username': 'admin', 'password': 'admin-pw'})
    assert response.status_code == 429
    assert 'Zu viele Fehlversuche' in flash_messages(response)[0]


def test_lock_applies_per_client_address_and_user_name():
    create_user('zweiter', 'Administrator')
    for _ in range(login_guard.MAX_ATTEMPTS):
        new_client().post('/admin/login', data={'username': 'admin', 'password': 'x'})
    assert login(new_client(ip='10.0.0.2'), 'admin', 'admin-pw'), "another address must not be locked"
    assert login(new_client(), 'zweiter', 'pw'), "another user from the locked address must not be locked"


def test_successful_login_resets_the_failure_counter():
    for _ in range(login_guard.MAX_ATTEMPTS - 1):
        new_client().post('/admin/login', data={'username': 'admin', 'password': 'x'})
    assert login(new_client(), 'admin', 'admin-pw')
    for _ in range(login_guard.MAX_ATTEMPTS - 1):
        new_client().post('/admin/login', data={'username': 'admin', 'password': 'x'})
    assert login(new_client(), 'admin', 'admin-pw')


def test_many_user_names_from_one_address_are_locked_too():
    statuses = [new_client().post('/admin/login', data={'username': f'name{i}', 'password': 'x'}).status_code
                for i in range(login_guard.MAX_ATTEMPTS_PER_CLIENT + 1)]
    assert statuses[-1] == 429
    assert statuses[login_guard.MAX_ATTEMPTS_PER_CLIENT - 1] == 200


def test_lock_is_written_to_the_change_log():
    for _ in range(login_guard.MAX_ATTEMPTS):
        new_client().post('/admin/login', data={'username': 'admin', 'password': 'x'})
    assert "Login locked" in open('change_log.txt', encoding='utf-8').read()


def test_role_change_takes_effect_in_a_running_session(admin):
    user_id = create_user('kollege', 'Administrator')
    colleague = new_client()
    assert login(colleague, 'kollege', 'pw')
    assert colleague.get('/api/schedules').status_code == 200
    admin.post(f'/admin/users/edit/{user_id}', data={'username': 'kollege', 'role': 'Betrachter'})
    assert colleague.get('/api/schedules').status_code == 403
    assert colleague.get('/api/logs').status_code == 200


def test_deleted_user_is_logged_out_at_once(admin):
    user_id = create_user('kollege', 'Benutzer')
    colleague = new_client()
    assert login(colleague, 'kollege', 'pw')
    admin.post(f'/admin/users/delete/{user_id}')
    assert colleague.get('/api/logs').status_code == 401


def test_every_role_can_change_its_own_password():
    viewer = client_for('Betrachter')
    wrong = viewer.post('/admin/users/reset_password/', follow_redirects=True,
                        data={'current_password': 'falsch', 'new_password': 'neu', 'confirm_password': 'neu'})
    assert 'Das aktuelle Passwort ist falsch.' in flash_messages(wrong)
    mismatch = viewer.post('/admin/users/reset_password/', follow_redirects=True,
                           data={'current_password': 'pw', 'new_password': 'neu', 'confirm_password': 'anders'})
    assert 'Die neuen Passwörter stimmen nicht überein.' in flash_messages(mismatch)
    done = viewer.post('/admin/users/reset_password/', follow_redirects=True,
                       data={'current_password': 'pw', 'new_password': 'neu', 'confirm_password': 'neu'})
    assert 'Das Passwort wurde geändert.' in flash_messages(done)
    assert login(new_client(), 'user-betrachter', 'neu')
    assert not login(new_client(), 'user-betrachter', 'pw')


def test_duplicate_user_name_gives_a_message_instead_of_an_error_page(admin):
    create_user('kollege', 'Benutzer')
    response = admin.post('/admin/users/add', data={'username': 'kollege', 'password': 'x', 'role': 'Benutzer'})
    assert response.status_code == 200
    assert 'bereits vergeben' in flash_messages(response)[0]
    user_id = create_user('dritter', 'Benutzer')
    response = admin.post(f'/admin/users/edit/{user_id}', data={'username': 'admin', 'role': 'Benutzer'})
    assert response.status_code == 200
    assert 'bereits vergeben' in flash_messages(response)[0]


def test_unknown_role_is_rejected(admin):
    response = admin.post('/admin/users/add', data={'username': 'x', 'password': 'x', 'role': 'Chef'})
    assert 'Unbekannte Rolle.' in flash_messages(response)


def test_own_account_and_last_administrator_are_protected(admin):
    conn = get_connection()
    admin_id = conn.execute("SELECT id FROM users WHERE username = 'admin'").fetchone()[0]
    conn.close()
    response = admin.post(f'/admin/users/delete/{admin_id}', follow_redirects=True)
    assert 'Das eigene Konto kann nicht gelöscht werden.' in flash_messages(response)
    response = admin.post(f'/admin/users/edit/{admin_id}', data={'username': 'admin', 'role': 'Benutzer'})
    assert 'Der letzte Administrator muss die Rolle Administrator behalten.' in flash_messages(response)
    assert login(new_client(), 'admin', 'admin-pw')


def test_users_survive_a_restart_and_keep_their_changed_password():
    from src.database import init_db
    create_user('kollege', 'Benutzer', password='eigenes')
    init_db()  # what the application does at every start
    assert login(new_client(), 'kollege', 'eigenes')
    assert read_config()['sensors'], "the configuration is untouched by a restart"


def test_other_sessions_end_when_the_password_is_changed():
    create_user('anna', 'Benutzer')
    here, elsewhere = new_client('10.0.0.1'), new_client('10.0.0.2')
    assert login(here, 'anna', 'pw') and login(elsewhere, 'anna', 'pw')
    assert elsewhere.get('/api/logs').status_code == 200
    done = here.post('/admin/users/reset_password/', follow_redirects=True,
                     data={'current_password': 'pw', 'new_password': 'neu', 'confirm_password': 'neu'})
    assert 'Das Passwort wurde geändert.' in flash_messages(done)
    assert here.get('/api/logs').status_code == 200, "the session that changed the password stays logged in"
    assert elsewhere.get('/api/logs').status_code == 401, "a session opened with the old password ends"
    assert elsewhere.get('/logs').status_code == 302
    # Other users are not affected
    assert client_for('Betrachter').get('/api/logs').status_code == 200


def test_session_from_before_the_update_is_bound_to_the_password_on_its_next_request():
    user_id = create_user('bert', 'Benutzer')
    client = new_client()
    with client.session_transaction() as session:  # as written by version 2.1.23: without the fingerprint
        session['user_id'], session['role'] = user_id, 'Benutzer'
    assert client.get('/api/logs').status_code == 200
    with client.session_transaction() as session:
        assert session['pw']
    conn = get_connection()
    conn.execute("UPDATE users SET password = 'anderer-hash' WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()
    assert client.get('/api/logs').status_code == 401
