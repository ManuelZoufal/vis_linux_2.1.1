from . import admin_bp

from src.helpers import login_required, log_change
from src.navigator import create_OAUTH_token
from src.database import get_connection

from flask import render_template, request, redirect, url_for, flash, session, current_app
from dotenv import set_key
import os
from werkzeug.security import check_password_hash, generate_password_hash
import sqlite3

ROLES = ('Administrator', 'Benutzer', 'Betrachter')


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
        username = request.form['username']
        password = request.form['password']
        remember = 'remember' in request.form

        conn = get_connection()
        user = conn.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
        conn.close()

        if user and check_password_hash(user['password'], password):
            session['user_id'] = user['id']
            session['role'] = user['role']
            if remember:
                session.permanent = True
            return redirect(url_for('admin.index'))
        else:
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
                conn.execute('UPDATE users SET username = ?, role = ? WHERE id = ?', (username, role, id))
                conn.commit()
            except sqlite3.IntegrityError:
                error = f'Der Benutzername „{username}“ ist bereits vergeben.'
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
    conn = get_connection()
    conn.execute('DELETE FROM users WHERE id = ?', (id,))
    conn.commit()
    conn.close()

    flash('Benutzer wurde gelöscht.', 'success')
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
