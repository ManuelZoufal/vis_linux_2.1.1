import socket
from datetime import datetime
from functools import wraps
from flask import session, redirect, url_for, jsonify

import os

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

def log_change(message):
    try:
        with open('change_log.txt', 'a') as log_file:
            log_file.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - {message}\n")
    except Exception as e:
        print(f"[LOG ERROR] Could not write to change_log.txt: {e}")


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
