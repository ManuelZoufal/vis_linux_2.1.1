from base64 import b64encode
import os
import time
import logging
import requests
from datetime import datetime, timezone
from requests.auth import HTTPDigestAuth

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

from src.database import get_connection

from requests.exceptions import ConnectionError, HTTPError, RequestException

# Load proxy settings from environment
PROXIES = {
    'http': 'http://185.46.212.88:80',
    'https': 'http://185.46.212.88:80'
}

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
            return response.json().get('access_token')
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

def upload_data_to_navigator(datapoint_id, occupancy, name):
    """
    Upload data to Navigator

    Args:
    sensors (list): List of sensors

    Returns:
    bool: True if data uploaded successfully, False otherwise

    Exception:
    Exception: If failed to upload data
    """

    try:
        token = create_OAUTH_token()
        if not token:
            return False

        timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:00.00Z')
        url = f"https://eadvantage.siemens.com/remote/release/meter/{datapoint_id}/readings"
        headers = {
            'accept': '*/*',
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {token}'
        }

        data = [{
            "comment": "",
            "correctionValue": "0.0",
            "qualityAttribute": "9",
            "utcRectime": timestamp,
            "value": occupancy
        }]

        time.sleep(0.01)
        response = requests.post(url, headers=headers, json=data, proxies=PROXIES, timeout=5)
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
            for sensor in rows:
                success = upload_data_to_navigator(sensor['datapoint_id'], sensor['occupancy'], sensor['sensor_name'])
                if not success:
                    logging.warning(f"Upload failed for {sensor['sensor_name']}")

        except Exception as e:
            logging.error(f"Navigator thread failed with error: {e}")

        time.sleep(interval)
