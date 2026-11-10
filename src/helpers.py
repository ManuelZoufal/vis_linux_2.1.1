import socket
from datetime import datetime
from functools import wraps
from flask import session, redirect, url_for

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


def login_required(role=None):
    """
    Decorator to check if user is logged in
    
    Args:
    role (str, optional): Role to check for
    """
    def wrapper(fn):
        @wraps(fn)
        def decorated_view(*args, **kwargs):
            if 'user_id' not in session:
                return redirect(url_for('admin.login'))
            if role and session.get('role') != role:
                return redirect(url_for('admin.login'))
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
