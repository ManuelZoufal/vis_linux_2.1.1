import logging
import time

import requests

from src import event_log

# (connect, read) timeout in seconds for all requests to a sensor
REQUEST_TIMEOUT = (5, 30)


def short_reason(error, response=None):
    """
    Describe a failed request in a few words

    Args:
    error (Exception): Exception raised by requests
    response (requests.Response, optional): Response, if one was received

    Returns:
    str: e.g. "HTTP 500 Internal Server Error" or "Zeitüberschreitung beim Verbindungsaufbau"
    """
    if error is None and response is None:
        return "unbekannter Fehler"
    if response is None:
        response = getattr(error, 'response', None)
    if response is not None and getattr(response, 'status_code', None):
        return f"HTTP {response.status_code} {getattr(response, 'reason', '') or ''}".strip()
    if isinstance(error, requests.exceptions.ConnectTimeout):
        return "Zeitüberschreitung beim Verbindungsaufbau"
    if isinstance(error, requests.exceptions.ReadTimeout):
        return "Zeitüberschreitung beim Warten auf die Antwort"
    if isinstance(error, requests.exceptions.SSLError):
        return event_log.shorten(f"TLS-Fehler: {error}", 160)
    # The innermost exception names the actual cause (e.g. RemoteDisconnected, ConnectionRefusedError)
    cause = error
    seen = set()
    while True:
        seen.add(id(cause))
        inner = cause.__cause__ or cause.__context__
        if inner is None:
            inner = next((a for a in getattr(cause, 'args', ()) if isinstance(a, BaseException)), None)
        if inner is None and isinstance(getattr(cause, 'reason', None), BaseException):
            inner = cause.reason
        if inner is None or id(inner) in seen:
            break
        cause = inner
    text = str(cause)
    if text.startswith('<') and ': ' in text:
        text = text.split(': ', 1)[1]  # drop "<... object at 0x...>: "
    return event_log.shorten(f"{type(cause).__name__}: {text}" if text else type(cause).__name__, 160)


class LoggingSession(requests.Session):
    """requests session that writes every request to the detail log while it is switched on"""

    def __init__(self, source):
        super().__init__()
        self.source = source

    def request(self, method, url, **kwargs):
        if not event_log.detail_active(self.source):
            return super().request(method, url, **kwargs)
        started = time.monotonic()
        try:
            response = super().request(method, url, **kwargs)
        except Exception as e:
            event_log.detail(self.source, f"{method.upper()} {url} | FEHLER {short_reason(e)} | {int((time.monotonic() - started) * 1000)} ms")
            raise
        # Never write what a login returns, it may contain a session token
        body = '(nicht protokolliert)' if 'login' in url else event_log.shorten(response.text, event_log.MAX_DETAIL_BODY)
        event_log.detail(self.source, f"{method.upper()} {url} | HTTP {response.status_code} | {int((time.monotonic() - started) * 1000)} ms | {body}")
        return response


class Sensor:
    def __init__(self, sensor_id, ip_address, name, sensor_type, group_id, datapoint_id):
        """
        Initialize Sensor object

        Args:
        sensor_id (int): Sensor ID
        ip_address (str): IP address of sensor
        name (str): Name of sensor
        sensor_type (str): Type of sensor
        group_id (int): Group ID
        datapoint_id (int): Datapoint ID
        """
        self.sensor_id = sensor_id
        self.ip_address = ip_address
        self.name = name
        self.sensor_type = sensor_type
        self.group_id = group_id
        self.datapoint_id = datapoint_id
        self.status = None
        self.forward_value = 0
        self.backward_value = 0
        self.occupancy = 0
        self.counting = True            # False: the device is not used for counting (e.g. heat map camera)
        self.last_error = None          # short reason of the last failed query
        self.last_action_error = None   # short reason of the last failed reset, reboot or login

    def log_info(self, message):
        """
        Log info message

        Args:
        message (str): Message to log
        """
        logging.info(f"{self.name}: {message}")

    def log_debug(self, message):
        """
        Log a routine message that is only of interest while debugging,
        e.g. every successful query (one per sensor every few seconds)

        Args:
        message (str): Message to log
        """
        logging.debug(f"{self.name}: {message}")

    def log_error(self, message):
        """
        Log error message

        Args:
        message (str): Message to log
        """
        self.last_error = event_log.shorten(message)
        logging.error(f"{self.name}: {message}")

    def log_failure(self, what, error, response=None, action=False, remember=True):
        """
        Log a failed request: the full text goes to the server log, a short
        reason is kept for the user interface and the event log

        Args:
        what (str): What failed, e.g. "Abfrage" or "Zurücksetzen"
        error (Exception): Exception raised by requests
        response (requests.Response, optional): Response, if one was received
        action (bool): True for reset, reboot and login (kept in last_action_error)
        remember (bool): False to only write the server log
        """
        reason = f"{what} fehlgeschlagen: {short_reason(error, response)}"
        if remember:
            if action:
                self.last_action_error = reason
            else:
                self.last_error = reason
        body = event_log.shorten(response.text, 500) if response is not None else 'keine Antwort'
        logging.error(f"{self.name}: {reason} | {event_log.shorten(error, 500)} | Antwort: {body}")

    def fetch_sensor_values(self):
        """
        Fetch sensor values
        """
        self.log_info("No fetch functionality available for this sensor")

    def reset_sensor_values(self):
        """
        Reset sensor values
        """
        self.log_info("No reset functionality available for this sensor")

    def reboot_sensor(self):
        """
        Reboot sensor
        """
        self.log_info("No reboot functionality available for this sensor")

    def check_credentials(self):
        """
        Check whether the sensor accepts the configured credentials

        Returns:
        tuple: (bool, str) - success and a short description
        """
        return False, "Keine Prüfung für diesen Sensortyp verfügbar"
