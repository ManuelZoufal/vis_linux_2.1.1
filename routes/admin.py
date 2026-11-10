from . import admin_bp

from src.helpers import login_required, log_change
from src.navigator import create_OAUTH_token
from src import login_guard
from src import sensor_credentials as credentials
from src.sensor import sensors as sensor_objects
from src.config_store import load_config, save_config, config_lock
from src.database import get_connection

from flask import render_template, request, redirect, url_for, flash, session, current_app
from dotenv import set_key, unset_key
from concurrent.futures import ThreadPoolExecutor
import os
from werkzeug.security import check_password_hash, generate_password_hash
import sqlite3

ROLES = ('Administrator', 'Benutzer', 'Betrachter')

# Hash of a random value, checked when the user name does not exist
_DUMMY_HASH = generate_password_hash(os.urandom(16).hex(), method='pbkdf2:sha256')


def _is_last_administrator(conn, user):
    """True if the user is the only remaining Administrator"""
    if user['role'] != 'Administrator':
        return False
    count = conn.execute("SELECT COUNT(*) FROM users WHERE role = 'Administrator'").fetchone()[0]
    return count <= 1


def _validate_user(username, role):
    """Return a description of the first problem, None if username and role are valid"""
    if not username:
        return 'Der Benutzername darf nicht leer sein.'
    if role not in ROLES:
        return 'Unbekannte Rolle.'
    return None

# /admin
@admin_bp.route('/', endpoint='index')
@login_required()
def admin_index():
    """Render the admin index page"""
    return render_template('admin/index.html')

# /admin/login
@admin_bp.route('/login', methods=['GET', 'POST'], endpoint='login')
def login():
    """Render the login page"""
    if request.method == 'POST':
        username = request.form.get('username', '')
        password = request.form.get('password', '')
        remember = 'remember' in request.form
        client = request.remote_addr or 'unknown'

        locked = login_guard.seconds_locked(client, username)
        if locked:
            flash(f'Zu viele Fehlversuche. Bitte in {(locked + 59) // 60} Minute(n) erneut versuchen.', 'error')
            return render_template('admin/login.html'), 429

        conn = get_connection()
        user = conn.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
        conn.close()

        # Always check a hash, so an unknown user name does not answer faster than a known one
        password_ok = check_password_hash(user['password'] if user else _DUMMY_HASH, password)
        if user and password_ok:
            login_guard.record_success(client, username)
            session.clear()
            session['user_id'] = user['id']
            session['role'] = user['role']
            if remember:
                session.permanent = True
            return redirect(url_for('admin.index'))

        if login_guard.record_failure(client, username):
            shown = ''.join(ch for ch in username if ch.isprintable())[:50]
            log_change(f"Login locked for {login_guard.LOCK_MINUTES} minutes after repeated failures: user '{shown}' from {client}")
        flash('Benutzername oder Passwort falsch!', 'error')

    return render_template('admin/login.html')

# /admin/logout
@admin_bp.route('/logout', endpoint='logout')
def logout():
    """Logout the user"""
    session.clear()
    return redirect(url_for('admin.login'))

# /admin/users
@admin_bp.route('/users', endpoint='manage_users')
@login_required(role='Administrator')
def manage_users():
    """Render the manage users page"""
    conn = get_connection()
    users = conn.execute('SELECT * FROM users').fetchall()
    conn.close()
    return render_template('admin/users.html', users=users)

# /admin/users/add
@admin_bp.route('/users/add', methods=['GET', 'POST'], endpoint='add_user')
@login_required(role='Administrator')
def add_user():
    """Add a new user"""
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        role = request.form.get('role', '')

        error = _validate_user(username, role)
        if not error and not password:
            error = 'Das Passwort darf nicht leer sein.'
        if not error:
            conn = get_connection()
            try:
                conn.execute('INSERT INTO users (username, password, role) VALUES (?, ?, ?)',
                             (username, generate_password_hash(password, method='pbkdf2:sha256'), role))
                conn.commit()
            except sqlite3.IntegrityError:
                error = f'Der Benutzername „{username}“ ist bereits vergeben.'
            finally:
                conn.close()
        if error:
            flash(error, 'error')
            return render_template('admin/add_user.html')

        flash(f'Benutzer „{username}“ wurde angelegt.', 'success')
        return redirect(url_for('admin.manage_users'))

    return render_template('admin/add_user.html')

# /admin/users/edit/<int:id>
@admin_bp.route('/users/edit/<int:id>', methods=['GET', 'POST'], endpoint='edit_user')
@login_required(role='Administrator')
def edit_user(id):
    """Edit a user"""
    conn = get_connection()
    user = conn.execute('SELECT * FROM users WHERE id = ?', (id,)).fetchone()
    conn.close()

    if user is None:
        flash('Benutzer nicht gefunden.', 'error')
        return redirect(url_for('admin.manage_users'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        role = request.form.get('role', '')

        error = _validate_user(username, role)
        if not error:
            conn = get_connection()
            try:
                if role != 'Administrator' and _is_last_administrator(conn, user):
                    raise ValueError('Der letzte Administrator muss die Rolle Administrator behalten.')
                conn.execute('UPDATE users SET username = ?, role = ? WHERE id = ?', (username, role, id))
                conn.commit()
            except sqlite3.IntegrityError:
                error = f'Der Benutzername „{username}“ ist bereits vergeben.'
            except ValueError as e:
                error = str(e)
            finally:
                conn.close()
        if error:
            flash(error, 'error')
            return render_template('admin/edit_user.html', user=user)

        flash(f'Benutzer „{username}“ wurde aktualisiert.', 'success')
        return redirect(url_for('admin.manage_users'))

    return render_template('admin/edit_user.html', user=user)

# /admin/users/delete/<int:id>
@admin_bp.route('/users/delete/<int:id>', methods=['POST'], endpoint='delete_user')
@login_required(role='Administrator')
def delete_user(id):
    """Delete a user"""
    if id == session.get('user_id'):
        flash('Das eigene Konto kann nicht gelöscht werden.', 'error')
        return redirect(url_for('admin.manage_users'))

    conn = get_connection()
    try:
        user = conn.execute('SELECT * FROM users WHERE id = ?', (id,)).fetchone()
        if user is None:
            flash('Benutzer nicht gefunden.', 'error')
        elif _is_last_administrator(conn, user):
            flash('Der letzte Administrator kann nicht gelöscht werden.', 'error')
        else:
            conn.execute('DELETE FROM users WHERE id = ?', (id,))
            conn.commit()
            flash(f'Benutzer „{user["username"]}“ wurde gelöscht.', 'success')
    finally:
        conn.close()
    return redirect(url_for('admin.manage_users'))

# /admin/users/reset_password/  (every logged in user changes the own password)
@admin_bp.route('/users/reset_password/', methods=['POST'], endpoint='reset_password')
@login_required()
def reset_password():
    """Change the password of the logged in user"""
    new_password = request.form.get('new_password', '')
    if not new_password:
        flash('Das neue Passwort darf nicht leer sein.', 'error')
        return redirect(url_for('admin.change_password'))
    if new_password != request.form.get('confirm_password', ''):
        flash('Die neuen Passwörter stimmen nicht überein.', 'error')
        return redirect(url_for('admin.change_password'))

    conn = get_connection()
    try:
        user = conn.execute('SELECT * FROM users WHERE id = ?', (session['user_id'],)).fetchone()
        if user is None or not check_password_hash(user['password'], request.form.get('current_password', '')):
            flash('Das aktuelle Passwort ist falsch.', 'error')
            return redirect(url_for('admin.change_password'))
        conn.execute('UPDATE users SET password = ? WHERE id = ?',
                     (generate_password_hash(new_password, method='pbkdf2:sha256'), session['user_id']))
        conn.commit()
    finally:
        conn.close()

    flash('Das Passwort wurde geändert.', 'success')
    return redirect(url_for('admin.index'))

# /admin/users/reset_password
@admin_bp.route('/users/reset_password', methods=['GET'] ,endpoint='change_password')
@login_required()
def change_password():
    """Render the change password page"""
    return render_template('admin/change_password.html')

# /admin/landing_page
@admin_bp.route('/landing_page', endpoint='landing_page')
@login_required()
def landing_page():
    """Render the landing page"""
    return render_template('admin/index.html')


# /admin/navigator
@admin_bp.route('/navigator', methods=['GET', 'POST'], endpoint='navigator')
@login_required(role='Administrator')
def navigator_credentials():
    """
    Show and change the Navigator credentials

    The values are written to the .env file and to the environment of the
    running process, so the next upload uses them without a restart.
    The password is never sent to the browser.
    """
    if request.method == 'POST':
        username = request.form.get('navigator_username', '').strip()
        password = request.form.get('navigator_password', '')
        if not username:
            flash('Der Benutzername darf nicht leer sein.', 'error')
            return redirect(url_for('admin.navigator'))

        values = {'NAVIGATOR_USERNAME': username}
        if password:
            values['NAVIGATOR_PASSWORD'] = password  # empty means: keep the stored password

        env_path = os.path.join(current_app.root_path, '.env')
        try:
            for key, value in values.items():
                set_key(env_path, key, value, quote_mode='always')
        except OSError as e:
            flash(f'Die Datei .env konnte nicht geschrieben werden: {e}', 'error')
            return redirect(url_for('admin.navigator'))
        os.environ.update(values)

        changed = 'Benutzername und Passwort' if password else 'Benutzername'
        log_change(f"Navigator credentials changed ({'username and password' if password else 'username'}) by user id {session.get('user_id')}")
        flash(f'Navigator-Zugangsdaten gespeichert ({changed}).', 'success')

        if request.form.get('action') == 'save_and_test':
            if create_OAUTH_token():
                flash('Verbindungstest erfolgreich: Navigator hat die Zugangsdaten akzeptiert.', 'success')
            else:
                flash('Verbindungstest fehlgeschlagen: Navigator hat kein Token ausgestellt. Details stehen im Server-Log.', 'error')
        return redirect(url_for('admin.navigator'))

    return render_template(
        'admin/navigator.html',
        username=os.environ.get('NAVIGATOR_USERNAME', ''),
        password_set=bool(os.environ.get('NAVIGATOR_PASSWORD')),
    )


def _write_env(set_values, remove_keys=()):
    """
    Write values to the .env file and to the environment of the running process

    Args:
    set_values (dict): Variable name -> value
    remove_keys (iterable): Variable names to delete

    Raises:
    OSError: If the .env file cannot be written
    """
    env_path = os.path.join(current_app.root_path, '.env')
    for key, value in set_values.items():
        set_key(env_path, key, value, quote_mode='always')
        os.environ[key] = value
    for key in remove_keys:
        if os.path.exists(env_path):
            unset_key(env_path, key, quote_mode='always')
        os.environ.pop(key, None)


SOURCE_LABELS = {
    credentials.SOURCE_SENSOR: 'Einzelwert (.env)',
    credentials.SOURCE_TYPE: 'Standard des Typs (.env)',
    credentials.SOURCE_CONFIG: 'config.json (alt)',
    credentials.SOURCE_MISSING: 'fehlt',
}
# Shown source of a sensor: the least favourable one of its fields
SOURCE_ORDER = (credentials.SOURCE_MISSING, credentials.SOURCE_CONFIG, credentials.SOURCE_SENSOR, credentials.SOURCE_TYPE)
TYPE_LABELS = {'IEE': 'IEE', 'AI_HANWHA': 'Hanwha'}


def _physical_sensors(config):
    return [s for s in config['sensors'] if s.get('type') in credentials.FIELDS_BY_TYPE]


def _check_all_sensors():
    """Check the credentials of all sensors in parallel and report the result as flash messages"""
    if not sensor_objects:
        return
    with ThreadPoolExecutor(max_workers=len(sensor_objects)) as pool:
        results = list(pool.map(lambda sensor: (sensor, *sensor.check_credentials()), sensor_objects))
    failed = [(sensor, message) for sensor, ok, message in results if not ok]
    if failed:
        flash(f'Prüfung: {len(results) - len(failed)} von {len(results)} Sensoren haben die Zugangsdaten akzeptiert.', 'error')
        for sensor, message in failed:
            flash(f'Sensor {sensor.sensor_id} ({sensor.name}): {message}', 'error')
    else:
        flash(f'Prüfung erfolgreich: alle {len(results)} Sensoren haben die Zugangsdaten akzeptiert.', 'success')


# /admin/sensor_credentials
@admin_bp.route('/sensor_credentials', methods=['GET', 'POST'], endpoint='sensor_credentials')
@login_required(role='Administrator')
def sensor_credentials_page():
    """
    Show and change the credentials of the sensors

    Values are written to the .env file, applied to the running sensor objects
    and never sent to the browser (passwords) or written to the change log.
    """
    if request.method == 'POST':
        action = request.form.get('action')
        try:
            if action == 'migrate':
                _migrate_from_config()
            else:
                _save_credentials_form()
                if action == 'save_and_test':
                    _check_all_sensors()
        except OSError as e:
            flash(f'Die Datei .env konnte nicht geschrieben werden: {e}', 'error')
        return redirect(url_for('admin.sensor_credentials'))

    config = load_config()
    physical = _physical_sensors(config)
    types = []
    for sensor_type, fields in credentials.FIELDS_BY_TYPE.items():
        key = credentials.TYPE_KEYS[sensor_type]
        types.append({
            'key': key,
            'label': TYPE_LABELS.get(sensor_type, sensor_type),
            'has_username': 'username' in fields,
            'username': os.environ.get(credentials.type_env_key(sensor_type, 'username'), '') if 'username' in fields else '',
            'password_set': bool(os.environ.get(credentials.type_env_key(sensor_type, 'password'))),
            'count': sum(1 for s in physical if s['type'] == sensor_type),
        })
    rows = []
    for sensor_config in physical:
        resolved = credentials.resolve(sensor_config)
        sources = {source for _value, source in resolved.values()}
        source = next(s for s in SOURCE_ORDER if s in sources)
        own_username = os.environ.get(credentials.sensor_env_key(sensor_config['sensor_id'], 'username'), '')
        own_password = bool(os.environ.get(credentials.sensor_env_key(sensor_config['sensor_id'], 'password')))
        rows.append({
            'sensor_id': sensor_config['sensor_id'],
            'name': sensor_config.get('name', ''),
            'type': TYPE_LABELS.get(sensor_config['type'], sensor_config['type']),
            'has_username': 'username' in resolved,
            'username': own_username if 'username' in resolved else '',
            'password_set': own_password,
            'has_own': bool(own_username) or own_password,
            'source': source,
            'source_label': SOURCE_LABELS[source],
        })
    legacy_count = sum(1 for s in physical if any(source == credentials.SOURCE_CONFIG for _v, source in credentials.resolve(s).values()))
    return render_template('admin/sensor_credentials.html', types=types, sensors=rows, legacy_count=legacy_count)


def _save_credentials_form():
    """Apply the submitted form: type defaults and values of single sensors"""
    config = load_config()
    physical = _physical_sensors(config)
    set_values, remove_keys, changed = {}, [], []

    for sensor_type, fields in credentials.FIELDS_BY_TYPE.items():
        key = credentials.TYPE_KEYS[sensor_type]
        if 'username' in fields:
            env_key = credentials.type_env_key(sensor_type, 'username')
            username = request.form.get(f'type_{key}_username', '').strip()
            if username and username != os.environ.get(env_key):
                set_values[env_key] = username
                changed.append(f'{key} username')
            elif not username and os.environ.get(env_key):
                remove_keys.append(env_key)
                changed.append(f'{key} username removed')
        password = request.form.get(f'type_{key}_password', '')
        if password:
            set_values[credentials.type_env_key(sensor_type, 'password')] = password
            changed.append(f'{key} password')

    for sensor_config in physical:
        sensor_id = sensor_config['sensor_id']
        fields = credentials.FIELDS_BY_TYPE[sensor_config['type']]
        own_keys = [credentials.sensor_env_key(sensor_id, field) for field in fields]
        if request.form.get(f'sensor_{sensor_id}_clear'):
            present = [k for k in own_keys if os.environ.get(k)]
            if present:
                remove_keys.extend(present)
                changed.append(f'sensor {sensor_id} own values removed')
            continue
        if 'username' in fields:
            env_key = credentials.sensor_env_key(sensor_id, 'username')
            username = request.form.get(f'sensor_{sensor_id}_username', '').strip()
            if username and username != os.environ.get(env_key):
                set_values[env_key] = username
                changed.append(f'sensor {sensor_id} username')
            elif not username and os.environ.get(env_key):
                remove_keys.append(env_key)
                changed.append(f'sensor {sensor_id} username removed')
        password = request.form.get(f'sensor_{sensor_id}_password', '')
        if password:
            set_values[credentials.sensor_env_key(sensor_id, 'password')] = password
            changed.append(f'sensor {sensor_id} password')

    if not changed:
        flash('Keine Änderungen.', 'success')
        return
    _write_env(set_values, remove_keys)
    credentials.apply_to_sensors(sensor_objects, config)
    log_change(f"Sensor credentials changed ({', '.join(changed)}) by user id {session.get('user_id')}")
    flash(f'Sensor-Zugangsdaten gespeichert ({len(changed)} Änderung(en)).', 'success')


def _migrate_from_config():
    """Move the credentials still stored in config.json to .env and remove them from config.json"""
    with config_lock:
        config = load_config()
        physical = _physical_sensors(config)
        before = {s['sensor_id']: {f: v for f, (v, _src) in credentials.resolve(s).items()} for s in physical}
        new_values = credentials.plan_migration(config)

        # Check first, change nothing yet: every sensor must get the same credentials without config.json
        simulated_env = {**os.environ, **new_values}
        stripped = {'sensors': [dict(s) for s in config['sensors']]}
        credentials.strip_from_config(stripped)
        after = {s['sensor_id']: {f: v for f, (v, _src) in credentials.resolve(s, simulated_env).items()}
                 for s in _physical_sensors(stripped)}
        # Compare what was configured before; a sensor without credentials may gain the type default
        unchanged = all(after.get(sensor_id, {}).get(field) == value
                        for sensor_id, fields in before.items() for field, value in fields.items() if value)
        if not unchanged:
            flash('Übernahme abgebrochen: Die Zugangsdaten wären danach nicht für alle Sensoren identisch. Es wurde nichts geändert.', 'error')
            return

        _write_env(new_values)                     # 1. .env (raises OSError before config.json is touched)
        removed = credentials.strip_from_config(config)
        save_config(config)                        # 2. config.json
        credentials.apply_to_sensors(sensor_objects, config)

    log_change(f"Sensor credentials moved from config.json to .env ({removed} sensors, {len(new_values)} variables) by user id {session.get('user_id')}")
    flash(f'Zugangsdaten von {removed} Sensor(en) aus config.json in die .env übernommen ({len(new_values)} Variable(n)).', 'success')
