import socket
from datetime import datetime
from functools import wraps
from flask import session, redirect, url_for, jsonify, request

import hashlib
import os
import threading

from src.database import get_connection
from src import event_log

UPLOAD_FOLDER = 'static/uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
MARQUEE_TEXT_FILE = 'static/uploads/marquee_text.txt'



def get_local_ip():
    """
    Get the local IP address of the machine
    
    Returns:
    str: Local IP address
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # doesn't even have to be reachable
        s.connect(('10.254.254.254', 1))
        local_ip = s.getsockname()[0]
    except Exception:
        local_ip = '127.0.0.1'
    finally:
        s.close()
    return local_ip

CHANGE_LOG_FILE = 'change_log.txt'
_change_log_lock = threading.Lock()


def log_change(message):
    """
    Write an entry to the change log

    The file is limited to LOG_MAX_MB like the other log files: when it is
    full it becomes change_log.txt.1 and a new one is started.

    Args:
    message (str): Description of the change
    """
    line = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - {event_log.shorten(message, 2000)}\n"
    try:
        with _change_log_lock:
            if os.path.exists(CHANGE_LOG_FILE) and os.path.getsize(CHANGE_LOG_FILE) + len(line.encode('utf-8')) > event_log.MAX_BYTES:
                os.replace(CHANGE_LOG_FILE, CHANGE_LOG_FILE + '.1')
            with open(CHANGE_LOG_FILE, 'a', encoding='utf-8') as log_file:
                log_file.write(line)
    except Exception as e:
        print(f"[LOG ERROR] Could not write to change_log.txt: {e}")


def password_fingerprint(password_hash):
    """
    Short value derived from the stored password hash. It is kept in the
    session, so sessions end when the password changes.

    Args:
    password_hash (str): Password hash as stored in the database
    """
    return hashlib.sha256(password_hash.encode('utf-8')).hexdigest()[:16]


def refresh_session_user():
    """
    Run before every request: take the role of the logged in user from the
    database, so a changed role applies immediately, and end the session if
    the user was deleted or the password was changed since the login.
    """
    if 'user_id' not in session or request.endpoint == 'static':
        return
    conn = get_connection()
    try:
        user = conn.execute('SELECT role, password FROM users WHERE id = ?', (session['user_id'],)).fetchone()
    finally:
        conn.close()
    if user is None:
        session.clear()
        return
    fingerprint = password_fingerprint(user['password'])
    if 'pw' not in session:
        session['pw'] = fingerprint  # session from before this check existed: it is bound to the password from now on
    elif session['pw'] != fingerprint:
        session.clear()  # the password was changed after this login
        return
    if session.get('role') != user['role']:
        session['role'] = user['role']


def _role_allowed(role):
    """
    Check if the role of the logged in user matches

    Args:
    role (str | tuple | list | None): Allowed role(s), None allows every logged in user
    """
    if not role:
        return True
    allowed = (role,) if isinstance(role, str) else role
    return session.get('role') in allowed


def login_required(role=None):
    """
    Decorator for pages: redirects to the login page if the user is not
    logged in or does not have one of the allowed roles

    Args:
    role (str | tuple | list, optional): Allowed role(s)
    """
    def wrapper(fn):
        @wraps(fn)
        def decorated_view(*args, **kwargs):
            if 'user_id' not in session:
                return redirect(url_for('admin.login'))
            if not _role_allowed(role):
                return redirect(url_for('admin.login'))
            return fn(*args, **kwargs)
        return decorated_view
    return wrapper


def api_login_required(role=None):
    """
    Decorator for API routes: answers with JSON instead of a redirect
    (401 if not logged in, 403 if the role is not allowed)

    Args:
    role (str | tuple | list, optional): Allowed role(s)
    """
    def wrapper(fn):
        @wraps(fn)
        def decorated_view(*args, **kwargs):
            if 'user_id' not in session:
                return jsonify({'status': 'error', 'message': 'Anmeldung erforderlich'}), 401
            if not _role_allowed(role):
                return jsonify({'status': 'error', 'message': 'Keine Berechtigung'}), 403
            return fn(*args, **kwargs)
        return decorated_view
    return wrapper

def allowed_file(filename):
    """
    Check if a file is allowed to be uploaded
    
    Args:
    filename (str): Name of the file
    """
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_marquee_text():
    """
    Get the marquee text
    
    Returns:
    str: Marquee text
    """
    if os.path.exists(MARQUEE_TEXT_FILE):
        with open(MARQUEE_TEXT_FILE, 'r') as file:
            return file.read()
    return ''
