from base64 import b64encode
import os
import threading
import time
import logging
import requests
from datetime import datetime, timezone
from requests.auth import HTTPDigestAuth

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

from src.database import get_connection
from src import thread_status

from requests.exceptions import ConnectionError, HTTPError, RequestException

# Load proxy settings from environment
PROXIES = {
    'http': 'http://185.46.212.88:80',
    'https': 'http://185.46.212.88:80'
}

# expires_in of the most recent token response (0 if the endpoint did not send it)
_last_token_lifetime = {'seconds': 0}


def create_OAUTH_token():
    """
    Create OAUTH token for Navigator API

    Returns:
    str: OAUTH token
    """

    url = "https://eadvantage.siemens.com/uaa/oauth/token"
    user = os.environ.get("NAVIGATOR_USERNAME")
    password = os.environ.get("NAVIGATOR_PASSWORD")

    if not user or not password:
        logging.error("Environment variables NAVIGATOR_USERNAME or NAVIGATOR_PASSWORD not set")
        return False

    credentials_raw = f"{user}:{password}"
    credentials = b64encode(credentials_raw.encode()).decode()


    try:
        headers = {
            'accept': '*/*',
            'Content-Type': 'application/x-www-form-urlencoded',
            'Authorization': f'Basic {credentials}'
        }
        response = requests.post(
            url, 
            headers=headers, 
            data="grant_type=client_credentials", 
            proxies=PROXIES,
            timeout=5
        )
        response.raise_for_status()
        if response.status_code == 200:
            logging.info("OAUTH token created successfully")
            body = response.json()
            try:
                _last_token_lifetime['seconds'] = int(body.get('expires_in') or 0)
            except (TypeError, ValueError):
                _last_token_lifetime['seconds'] = 0
            return body.get('access_token')
        else:
            logging.error(f"Failed to create OAUTH token. Status: {response.status_code}, Response: {response.text}")
            return False

    except ConnectionError as e:
        logging.error(f"[ConnectionError] Failed to connect to token endpoint: {e}")
        return False

    except HTTPError as e:
        logging.error(f"[HTTPError] Received HTTP error: {e.response.status_code} - {e.response.text}")
        return False

    except RequestException as e:
        logging.error(f"[RequestException] General requests error: {e}")
        return False

    except Exception as e:
        logging.error(f"[Exception] Unexpected error: {e}")
        return False

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


def get_token():
    """
    Get a token for the Navigator API, from the cache if it is still valid

    A new token is requested if none is cached, the cached one is about to
    expire or the credentials in the environment have changed.

    Returns:
    str: OAUTH token, False if no token could be created
    """
    credentials = (os.environ.get("NAVIGATOR_USERNAME"), os.environ.get("NAVIGATOR_PASSWORD"))
    with _token_lock:
        if _token_cache['token'] and _token_cache['credentials'] == credentials and time.time() < _token_cache['expires_at']:
            return _token_cache['token']
        token = create_OAUTH_token()
        if not token:
            _token_cache.update(token=None, expires_at=0.0, credentials=None)
            return False
        lifetime = _last_token_lifetime.get('seconds')
        if lifetime:
            lifetime = max(lifetime - TOKEN_EXPIRY_MARGIN, 1)
        else:
            lifetime = TOKEN_DEFAULT_LIFETIME
        _token_cache.update(token=token, expires_at=time.time() + lifetime, credentials=credentials)
        return token


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
            response = requests.post(url, headers=headers, json=data, proxies=PROXIES, timeout=5)
            if response.status_code == 401 and attempt == 1:
                logging.info("Navigator rejected the cached token, requesting a new one")
                clear_token_cache()
                continue
            break

        if response.status_code == 201:
            logging.info(f"Data uploaded to Navigator for sensor {name}")
            return True
        else:
            logging.error(f"Failed to upload data to Navigator for sensor {name}. Status: {response.status_code}, Response: {response.text}")
            return False

    except Exception as e:
        logging.error(f"Exception during upload for sensor {name}: {e}")
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
                thread_status.report_error("Kein Token von Navigator erhalten (Zugangsdaten oder Verbindung prüfen)")
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
