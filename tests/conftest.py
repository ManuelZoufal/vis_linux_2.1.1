"""
Test setup

The application reads config.json, the database and its log files relative to
the working directory and loads the sensors when its modules are imported.
Therefore this file, which pytest imports before any test module, creates a
temporary working directory with its own configuration, switches to it and
sets the environment before the application is imported. The repository
itself is never written to.

Every test starts from the same state (see the fixture `fresh_state`), and
requests to anything but 127.0.0.1 fail, so no test can reach a real sensor
or Navigator.
"""
import copy
import json
import os
import pathlib
import shutil
import sys
import tempfile
import threading

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
WORK = pathlib.Path(tempfile.mkdtemp(prefix='vis-tests-'))
ENV_FILE = WORK / 'test.env'
BASE_URL = 'https://localhost'

BASE_CONFIG = {
    "sensors": [
        {"sensor_id": "1", "type": "AI_HANWHA", "ip_address": "192.0.2.1", "name": "KAM1 | Eingang",
         "group_id": "1", "username": "admin", "password": "kam-alt", "datapoint_id": "1001"},
        {"sensor_id": "2", "type": "IEE", "ip_address": "192.0.2.2", "name": "IEE2 | Eingang",
         "group_id": "1", "password": "iee-alt", "datapoint_id": "1002"},
        {"sensor_id": "3", "type": "IEE", "ip_address": "192.0.2.3", "name": "IEE3 | Ausgang",
         "group_id": "2", "password": "iee-alt", "datapoint_id": "1003"},
        {"sensor_id": "10", "type": "AI_HANWHA", "ip_address": "192.0.2.10", "name": "KAM10 | Heatmap",
         "group_id": "2", "username": "admin", "password": "kam-alt", "datapoint_id": ""},
    ],
    "groups": [
        {"group_id": "1", "name": "Gruppe Eins", "max_occupancy": "150", "welcome_text": "Willkommen",
         "maintenance_mode": False, "display_images": [None, None, None]},
        {"group_id": "2", "name": "Gruppe Zwei", "max_occupancy": 80, "welcome_text": "Hallo",
         "maintenance_mode": False},
        {"group_id": "3", "name": "Leere Gruppe", "max_occupancy": 10, "welcome_text": "", "maintenance_mode": True},
    ],
    "schedules": [
        {"id": 1, "action": "reset", "interval": "daily", "day": "monday", "time": "07:00", "sensors": ["1", "2"]},
    ],
}

BASE_ENV = {
    'APP_SECRET_KEY': 'test-secret',
    'APP_DEBUG': 'false',
    'APP_PORT': '5000',
    'DEFAULT_ADMIN_USER': 'admin',
    'DEFAULT_ADMIN_PASSWORD': 'admin-pw',
    'NAVIGATOR_USERNAME': 'nav-user',
    'NAVIGATOR_PASSWORD': 'nav-pw',
    'LOG_DIR': str(WORK / 'logs'),
}


def write_config(config=None):
    (WORK / 'config.json').write_text(json.dumps(config or BASE_CONFIG, indent=4), encoding='utf-8')


def read_config():
    return json.loads((WORK / 'config.json').read_text(encoding='utf-8'))


def _clean_environment():
    for key in list(os.environ):
        if key.startswith('SENSOR_') or key in ('LOG_MAX_MB', 'APP_TIMEZONE', 'CERT_WARN_DAYS'):
            del os.environ[key]
    os.environ.update(BASE_ENV)


# ---- before the application is imported --------------------------------------
os.chdir(WORK)
write_config()
_clean_environment()
sys.path.insert(0, str(ROOT))

import requests  # noqa: E402
import schedule as schedule_lib  # noqa: E402

import app as app_module  # noqa: E402
import routes.admin as admin_routes  # noqa: E402
from src import certificate, event_log, login_guard, navigator, sensor, server_log, thread_status  # noqa: E402
from src.database import init_db, get_connection  # noqa: E402
from werkzeug.security import generate_password_hash  # noqa: E402
from flask.testing import FlaskClient  # noqa: E402

flask_app = app_module.app
init_db()


def fast_hash(password):
    """Password hash with a single iteration: the real cost would make every login in the tests take a quarter second"""
    return generate_password_hash(password, method='pbkdf2:sha256:1')


_real_request = requests.sessions.Session.request
_real_set_key = admin_routes.set_key
_real_unset_key = admin_routes.unset_key


def _local_only_request(self, method, url, **kwargs):
    """Tests must never reach a real device: only the loopback address is allowed"""
    if '://127.0.0.1' not in url:
        raise AssertionError(f"Test tried to reach the network: {method} {url}")
    return _real_request(self, method, url, **kwargs)


def pytest_sessionfinish(session, exitstatus):
    os.chdir(ROOT)
    shutil.rmtree(WORK, ignore_errors=True)


@pytest.fixture(autouse=True)
def fresh_state(monkeypatch):
    """Bring files, database and all module level state back to the starting point"""
    monkeypatch.setattr(requests.sessions.Session, 'request', _local_only_request)
    # The admin pages write to .env next to app.py: redirect that to the temporary directory
    monkeypatch.setattr(admin_routes, 'set_key', lambda path, *a, **kw: _real_set_key(str(ENV_FILE), *a, **kw))
    monkeypatch.setattr(admin_routes, 'unset_key', lambda path, *a, **kw: _real_unset_key(str(ENV_FILE), *a, **kw))
    monkeypatch.setattr(admin_routes.os.path, 'exists',
                        lambda path, _real=os.path.exists: _real(str(ENV_FILE)) if str(path).endswith('.env') else _real(path))

    _clean_environment()
    write_config()
    for name in ('change_log.txt', 'change_log.txt.1', 'test.env'):
        if (WORK / name).exists():
            (WORK / name).unlink()
    shutil.rmtree(WORK / 'logs', ignore_errors=True)
    shutil.rmtree(WORK / 'static', ignore_errors=True)

    event_log.stop_detail('Testende')
    event_log._detail.update(path=None, until=0.0, scope='all', started=None, bytes=0, stop_reason=None)
    event_log.MAX_BYTES = 200 * 1024 * 1024
    event_log.DETAIL_KEEP_FILES = 5
    event_log.init()
    server_log.stop('Testende')
    server_log.init(False)
    server_log._state['last_stop_reason'] = None

    # The database is created once (see below); per test only its content is reset.
    # init_db() would hash the admin password with full cost every time.
    conn = get_connection()
    conn.execute("DELETE FROM sensor_data")
    conn.execute("DELETE FROM users WHERE username != 'admin'")
    conn.execute("UPDATE users SET password = ?, role = 'Administrator' WHERE username = 'admin'", (fast_hash('admin-pw'),))
    conn.commit()
    conn.close()

    sensor.sensors[:] = sensor.load_sensors_from_config('config.json')
    schedule_lib.clear()
    thread_status._entries.clear()
    login_guard._failures.clear()
    navigator.clear_token_cache()
    navigator._backoff.update(failures=0, retry_at=0.0, credentials=None)
    navigator._last_token_error['reason'] = None
    navigator._last_token_lifetime['seconds'] = 0
    certificate._loaded.update(not_after=None, names=[], mtime=None, error=None)
    yield
    schedule_lib.clear()
    server_log.stop('Testende')
    event_log.stop_detail('Testende')


# ---- helpers -----------------------------------------------------------------

class HttpsClient(FlaskClient):
    """Test client that talks HTTPS, like a browser does with the real application
    (plain HTTP requests are redirected by the application)"""

    def open(self, *args, **kwargs):
        kwargs.setdefault('base_url', BASE_URL)
        return super().open(*args, **kwargs)


flask_app.test_client_class = HttpsClient


def new_client(ip='10.0.0.1'):
    client = flask_app.test_client()
    client.environ_base['REMOTE_ADDR'] = ip
    return client


def login(client, username, password):
    response = client.post('/admin/login', data={'username': username, 'password': password})
    return response.status_code == 302 and response.headers['Location'].rstrip('/').endswith('/admin')


def create_user(username, role, password='pw'):
    conn = get_connection()
    conn.execute('INSERT INTO users (username, password, role) VALUES (?, ?, ?)', (username, fast_hash(password), role))
    conn.commit()
    user_id = conn.execute('SELECT id FROM users WHERE username = ?', (username,)).fetchone()[0]
    conn.close()
    return user_id


def client_for(role):
    """Logged in client with the given role; None gives an anonymous client"""
    client = new_client()
    if role is None:
        return client
    if role == 'Administrator':
        assert login(client, 'admin', 'admin-pw')
        return client
    username = f"user-{role.lower()}"
    conn = get_connection()
    exists = conn.execute('SELECT 1 FROM users WHERE username = ?', (username,)).fetchone()
    conn.close()
    if not exists:
        create_user(username, role)
    assert login(client, username, 'pw')
    return client


def run_in_thread(name, function):
    """The thread status identifies a thread by its name, so reports must come from a thread with that name"""
    result = {}

    def target():
        try:
            result['value'] = function()
        except BaseException as error:  # noqa: BLE001 - handed to the calling test
            result['error'] = error

    thread = threading.Thread(target=target, name=name)
    thread.start()
    thread.join()
    if 'error' in result:
        raise result['error']
    return result.get('value')


def flash_messages(response):
    import re
    return [m.strip() for m in re.findall(r'flash-message \w+">([^<]*)', response.get_data(as_text=True))]


@pytest.fixture
def admin():
    return client_for('Administrator')


@pytest.fixture
def anonymous():
    return client_for(None)


@pytest.fixture
def sensors():
    return {s.sensor_id: s for s in sensor.sensors}


@pytest.fixture
def config():
    return copy.deepcopy(BASE_CONFIG)
