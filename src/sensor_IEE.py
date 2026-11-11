import requests

import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from src.sensor_base import Sensor, LoggingSession, REQUEST_TIMEOUT
from src.database import save_sensor_values

class IEE(Sensor):
    def __init__(self, sensor_id, ip_address, name, group_id, password, datapoint_id):
        """
        Initialize IEE sensor object
        
        Args:
        sensor_id (int): Sensor ID
        ip_address (str): IP address of sensor
        name (str): Name of sensor
        group_id (int): Group ID
        password (str): Password for sensor
        datapoint_id (int): Datapoint ID
        """
        super().__init__(sensor_id, ip_address, name, "IEE", group_id, datapoint_id)
        self.password = password
        self.session = LoggingSession(f"SensorThread-{sensor_id}")

    def fetch_sensor_values(self):
        """
        Fetch sensor values from sensor and save to database

        Returns:
        bool: True if values fetched successfully, False
        otherwise
        """
        url = f"https://{self.ip_address}/webservice/getoutput"
        response = None
        try:
            response = self.session.get(url, verify=False, timeout=REQUEST_TIMEOUT, proxies={})
            response.raise_for_status()
            data = response.json()
            self.forward_value = data["counters"]["total_forward_dir"]
            self.backward_value = data["counters"]["total_backward_dir"]
            self.occupancy = self.forward_value - self.backward_value
            save_sensor_values(self)
            self.log_info(f"Sensor values fetched successfully for sensor {self.name}, Response: {response.text}")
            return True
        except requests.RequestException as e:
            self.log_failure('Abfrage', e, response)
            return False
        
    def reset_sensor_values(self):
        """
        Reset sensor values

        Returns:
        bool: True if values reset successfully, False otherwise
        """
        self.last_action_error = None
        if self._authenticate():
            url = f"https://{self.ip_address}/webservice/reset_counters"
            response = None
            try:
                response = self.session.post(url, verify=False, timeout=REQUEST_TIMEOUT, proxies={})
                response.raise_for_status()
                self.log_info(f"Sensor values reset successfully. Response: {response.text}")
                return True
            except requests.RequestException as e:
                self.log_failure('Zurücksetzen', e, response, action=True)
                return False
            finally:
                self._logout()
        
    def reboot_sensor(self):
        """
        Reboot sensor

        Returns:
        bool: True if sensor rebooted successfully, False
        otherwise
        """
        self.last_action_error = None
        if self._authenticate():
            url = f"https://{self.ip_address}/webservice/reboot"
            response = None
            try:
                response = self.session.post(url, verify=False, timeout=REQUEST_TIMEOUT, proxies={})
                response.raise_for_status()
                self.log_info(f"Sensor rebooted successfully. Response: {response.text}")
                return True
            except requests.RequestException as e:
                self.log_failure('Neustart', e, response, action=True)
                return False
            finally:
                self._logout()

    def _authenticate(self):
        """
        Authenticate sensor

        Returns:
        bool: True if authenticated successfully, False
        otherwise
        """
        url = f"https://{self.ip_address}/webservice/login"
        response = None
        try:
            response = self.session.post(url, json={'password': self.password}, verify=False, timeout=REQUEST_TIMEOUT, proxies={})
            response.raise_for_status()
            self.log_info(f"Authenticated successfully. Response: {response.text}")
            return True
        except requests.RequestException as e:
            self.log_failure('Anmeldung', e, response, action=True)
            return False
        
    def _logout(self):
        """
        Logout sensor

        Returns:
        bool: True if logged out successfully, False otherwise
        """
        url = f"https://{self.ip_address}/webservice/logout"
        response = None
        try:
            response = self.session.post(url, verify=False, timeout=REQUEST_TIMEOUT, proxies={})
            response.raise_for_status()
            self.log_info(f"Logged out successfully. Response: {response.text}")
            return True
        except requests.RequestException as e:
            self.log_failure('Abmeldung', e, response, remember=False)
            return False

    def check_credentials(self):
        """
        Check the password by logging in and out again

        Returns:
        tuple: (bool, str) - success and a short description
        """
        if not self.password:
            return False, "Kein Passwort hinterlegt"
        url = f"https://{self.ip_address}/webservice/login"
        try:
            response = self.session.post(url, json={'password': self.password}, verify=False, timeout=REQUEST_TIMEOUT, proxies={})
        except requests.RequestException as e:
            return False, f"Sensor nicht erreichbar ({type(e).__name__})"
        if response.status_code in (401, 403):
            return False, f"Anmeldung abgelehnt (HTTP {response.status_code})"
        if not response.ok:
            return False, f"Unerwartete Antwort (HTTP {response.status_code})"
        self._logout()
        return True, "Anmeldung erfolgreich"
