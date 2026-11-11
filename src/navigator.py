from base64 import b64encode
import os
import threading
import time
import logging
import requests
from datetime import datetime, timezone

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

from src.database import get_connection
from src import thread_status
from src import event_log
from src.sensor_base import short_reason


# Load proxy settings from environment
PROXIES = {
    'http': 'http://185.46.212.88:80',
    'https': 'http://185.46.212.88:80'
}

# expires_in of the most recent token response (0 if the endpoint did not send it)
_last_token_lifetime = {'seconds': 0}


SOURCE = 'NavigatorUploadThread'
TOKEN_URL = "https://eadvantage.siemens.com/uaa/oauth/token"

# Why the most recent token request failed (None after a success), for the user interface
_last_token_error = {'reason': None}


def last_token_error():
    """Short reason why the last token request failed, None if it succeeded"""
    return _last_token_error['reason']


def create_OAUTH_token():
    """
    Create OAUTH token for Navigator API (always a real request, no cache)

    Returns:
    str: OAUTH token, False if no token could be created
    """
    user = os.environ.get("NAVIGATOR_USERNAME")
    password = os.environ.get("NAVIGATOR_PASSWORD")

    if not user or not password:
        logging.error("Environment variables NAVIGATOR_USERNAME or NAVIGATOR_PASSWORD not set")
        _last_token_error['reason'] = "Benutzername oder Passwort nicht hinterlegt"
        return False

    credentials = b64encode(f"{user}:{password}".encode()).decode()
    headers = {
        'accept': '*/*',
        'Content-Type': 'application/x-www-form-urlencoded',
        'Authorization': f'Basic {credentials}'
    }
    started = time.monotonic()
    try:
        response = requests.post(TOKEN_URL, headers=headers, data="grant_type=client_credentials", proxies=PROXIES, timeout=5)
    except Exception as e:
        reason = short_reason(e)
        logging.error(f"Token request to Navigator failed: {reason} | {e}")
        _last_token_error['reason'] = reason
        # The response of the token endpoint is never written to the detail log, it contains the token
        event_log.detail(SOURCE, f"POST {TOKEN_URL} | FEHLER {reason} | {int((time.monotonic() - started) * 1000)} ms")
        return False

    event_log.detail(SOURCE, f"POST {TOKEN_URL} | HTTP {response.status_code} | {int((time.monotonic() - started) * 1000)} ms | (nicht protokolliert)")
    if response.status_code != 200:
        logging.error(f"Failed to create OAUTH token. Status: {response.status_code}, Response: {event_log.shorten(response.text, 300)}")
        _last_token_error['reason'] = f"HTTP {response.status_code} {response.reason or ''}".strip()
        return False
    try:
        body = response.json()
        token = body.get('access_token')
    except ValueError:
        body, token = {}, None
    if not token:
        _last_token_error['reason'] = "Antwort ohne Token"
        return False
    try:
        _last_token_lifetime['seconds'] = int(body.get('expires_in') or 0)
    except (TypeError, ValueError):
        _last_token_lifetime['seconds'] = 0
    logging.info("OAUTH token created successfully")
    _last_token_error['reason'] = None
    _backoff['retry_at'] = 0.0  # also ends the throttling when the test on the admin page succeeds
    return token


# ---- Token cache -------------------------------------------------------------
# One token is reused for all uploads until it expires, instead of requesting a
# new one for every sensor.
TOKEN_EXPIRY_MARGIN = 60      # seconds a token is renewed before it expires
TOKEN_DEFAULT_LIFETIME = 50   # seconds, used if the token endpoint does not send expires_in

_token_lock = threading.Lock()
_token_cache = {'token': None, 'expires_at': 0.0, 'credentials': None}


def clear_token_cache():
    """Forget the cached token, the next upload requests a new one"""
    with _token_lock:
        _token_cache.update(token=None, expires_at=0.0, credentials=None)


# After this many failed token requests in a row the next one is only made every
# NAVIGATOR_RETRY_MINUTES, so wrong or expired credentials do not cause a request per minute
BACKOFF_AFTER_FAILURES = 5
RETRY_MINUTES = int(os.environ.get('NAVIGATOR_RETRY_MINUTES', 15))

_backoff = {'failures': 0, 'retry_at': 0.0, 'credentials': None}


def retry_time():
    """Time of the next token request while requests are throttled, None otherwise"""
    with _token_lock:
        if _backoff['retry_at'] > time.time():
            return datetime.fromtimestamp(_backoff['retry_at']).strftime('%H:%M')
    return None


def get_token():
    """
    Get a token for the Navigator API, from the cache if it is still valid

    A new token is requested if none is cached, the cached one is about to
    expire or the credentials in the environment have changed. After repeated
    failures requests are throttled until one succeeds or the credentials change.

    Returns:
    str: OAUTH token, False if no token could be created
    """
    credentials = (os.environ.get("NAVIGATOR_USERNAME"), os.environ.get("NAVIGATOR_PASSWORD"))
    throttled = None
    with _token_lock:
        if _token_cache['token'] and _token_cache['credentials'] == credentials and time.time() < _token_cache['expires_at']:
            return _token_cache['token']
        was_throttled = _backoff['failures'] >= BACKOFF_AFTER_FAILURES
        if _backoff['credentials'] != credentials:
            _backoff.update(failures=0, retry_at=0.0, credentials=credentials)  # new credentials: try at once
        if time.time() < _backoff['retry_at']:
            return False
        token = create_OAUTH_token()
        if not token:
            _token_cache.update(token=None, expires_at=0.0, credentials=None)
            _backoff['failures'] += 1
            if _backoff['failures'] >= BACKOFF_AFTER_FAILURES:
                _backoff['retry_at'] = time.time() + RETRY_MINUTES * 60
                if _backoff['failures'] == BACKOFF_AFTER_FAILURES:
                    throttled = (f"Nach {BACKOFF_AFTER_FAILURES} Fehlversuchen in Folge wird nur noch alle {RETRY_MINUTES} Minuten "
                                 f"ein Token angefordert ({last_token_error()})")
        else:
            _backoff.update(failures=0, retry_at=0.0)
            lifetime = _last_token_lifetime.get('seconds')
            if lifetime:
                lifetime = max(lifetime - TOKEN_EXPIRY_MARGIN, 1)
            else:
                lifetime = TOKEN_DEFAULT_LIFETIME
            _token_cache.update(token=token, expires_at=time.time() + lifetime, credentials=credentials)
            if was_throttled:
                throttled = "Token wieder erhalten, Anfragen laufen wieder im normalen Takt"
    if throttled:
        event_log.event('navigator', SOURCE, throttled, 'Navigator-Upload')
    return token or False


def has_datapoint(datapoint_id):
    """True if a sensor has a Navigator datapoint assigned"""
    return bool(str(datapoint_id or '').strip()) and str(datapoint_id).strip().upper() != 'N/A'


def upload_data_to_navigator(datapoint_id, occupancy, name):
    """
    Upload data to Navigator

    Args:
    datapoint_id (str): Navigator datapoint of the sensor
    occupancy (int): Value to upload
    name (str): Name of the sensor (for the log)

    Returns:
    bool: True if data uploaded successfully, False otherwise
    """
    if not has_datapoint(datapoint_id):
        logging.warning(f"No Navigator datapoint configured for sensor {name}, upload skipped")
        return False

    try:
        timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:00.00Z')
        url = f"https://eadvantage.siemens.com/remote/release/meter/{datapoint_id}/readings"
        data = [{
            "comment": "",
            "correctionValue": "0.0",
            "qualityAttribute": "9",
            "utcRectime": timestamp,
            "value": occupancy
        }]

        # Second attempt only if Navigator rejects the cached token
        for attempt in (1, 2):
            token = get_token()
            if not token:
                return False
            headers = {
                'accept': '*/*',
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {token}'
            }
            started = time.monotonic()
            response = requests.post(url, headers=headers, json=data, proxies=PROXIES, timeout=5)
            event_log.detail(SOURCE, f"POST {url} | HTTP {response.status_code} | {int((time.monotonic() - started) * 1000)} ms "
                                     f"| Wert {occupancy} | {event_log.shorten(response.text, event_log.MAX_DETAIL_BODY)}")
            if response.status_code == 401 and attempt == 1:
                logging.info("Navigator rejected the cached token, requesting a new one")
                clear_token_cache()
                continue
            break

        if response.status_code == 201:
            logging.debug(f"Data uploaded to Navigator for sensor {name}")  # one per sensor and minute
            return True
        else:
            logging.error(f"Failed to upload data to Navigator for sensor {name}. Status: {response.status_code}, Response: {event_log.shorten(response.text, 300)}")
            return False

    except Exception as e:
        logging.error(f"Exception during upload for sensor {name}: {e}")
        event_log.detail(SOURCE, f"POST Messwert für {name} | FEHLER {short_reason(e)}")
        return False

def navigator_thread(interval):
    """
    Navigator thread

    Args:
    interval (int): Interval in seconds
    """
    while True:
        try:

            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM sensor_data')
            rows = cursor.fetchall()
            conn.close()
            failed = 0
            uploaded = 0
            skipped = 0
            # Without a token no upload can succeed: one failed request per cycle instead of one per sensor
            if any(has_datapoint(sensor['datapoint_id']) for sensor in rows) and not get_token():
                retry = retry_time()
                thread_status.report_error(f"Kein Token von Navigator erhalten: {last_token_error() or 'unbekannter Grund'}"
                                           + (f"; nächster Versuch um {retry}" if retry else "")
                                           + " (Zugangsdaten unter Navigator-Zugang prüfen)")
                time.sleep(interval)
                continue
            for sensor in rows:
                if not has_datapoint(sensor['datapoint_id']):
                    skipped += 1  # no Navigator datapoint assigned: nothing to upload
                    continue
                if upload_data_to_navigator(sensor['datapoint_id'], sensor['occupancy'], sensor['sensor_name']):
                    uploaded += 1
                else:
                    failed += 1
                    logging.warning(f"Upload failed for {sensor['sensor_name']}")
            skipped_text = f", {skipped} ohne Datenpunkt übersprungen" if skipped else ""
            if failed:
                thread_status.report_error(f"{failed} von {uploaded + failed} Uploads fehlgeschlagen{skipped_text}")
            else:
                thread_status.report_success(f"{uploaded} Uploads{skipped_text}")

        except Exception as e:
            logging.error(f"Navigator thread failed with error: {e}")
            thread_status.report_error(f"{type(e).__name__}: {e}")

        time.sleep(interval)
