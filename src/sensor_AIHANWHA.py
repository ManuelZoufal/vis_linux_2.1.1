import requests

from requests.auth import HTTPDigestAuth
from requests.exceptions import RequestException

from src.database import save_sensor_values
from src.sensor_base import Sensor, LoggingSession, REQUEST_TIMEOUT

class AI_HANWHA(Sensor):
    def __init__(self, sensor_id, ip_address, name, group_id, username, password, datapoint_id):
        """
        Initialize AI_HANWHA sensor object
        
        Args:
        sensor_id (int): Sensor ID
        ip_address (str): IP address of sensor
        name (str): Name of sensor
        group_id (int): Group ID
        username (str): Username for sensor
        password (str): Password for sensor
        datapoint_id (int): Datapoint ID
        """
        super().__init__(sensor_id, ip_address, name, "AI_HANWHA", group_id, datapoint_id)
        self.password = password
        self.username = username
        self.session = LoggingSession(f"SensorThread-{sensor_id}")

    def fetch_sensor_values(self):
        """
        Fetch sensor values from sensor and save to database

        Returns:
        bool: True if values fetched successfully, False
        otherwise
        """

        protocols = ["http"]

        for protocol in protocols:
            url = f"{protocol}://{self.ip_address}/stw-cgi/eventsources.cgi?msubmenu=peoplecount&action=check&Channel=0"
            try:
                response = self.session.get(url, auth=HTTPDigestAuth(self.username, self.password), verify=False, timeout=REQUEST_TIMEOUT, proxies={"http": None, "https": None})
                response.raise_for_status()
                data = response.text.split("\r")
                forward_value_line1 = next((int(line.split('=')[1]) for line in data if 'Channel.0.LineIndex.1.InCount' in line), 0)
                backward_value_line1 = next((int(line.split('=')[1]) for line in data if 'Channel.0.LineIndex.1.OutCount' in line), 0)
                forward_value_line2 = next((int(line.split('=')[1]) for line in data if 'Channel.0.LineIndex.2.InCount' in line), 0)
                backward_value_line2 = next((int(line.split('=')[1]) for line in data if 'Channel.0.LineIndex.2.OutCount' in line), 0)
                self.forward_value = forward_value_line1 + forward_value_line2
                self.backward_value = backward_value_line1 + backward_value_line2
                self.occupancy = self.forward_value - self.backward_value
                save_sensor_values(self)
                self.log_info(f"Sensor values fetched successfully for sensor {self.name} via {protocol.upper()}, Response: {response.text}")
                return True

            except RequestException as e:
                self.log_failure('Abfrage', e)
                return False

        return False

    def reset_sensor_values(self):
        """
        Reset sensor values"
        """
        self.last_action_error = None
        url = f"https://{self.ip_address}/stw-cgi/system.cgi?msubmenu=databasereset&action=control&IncludeDataType=PeopleCount"
        response = None
        try:
            response = self.session.post(url, auth=HTTPDigestAuth(self.username, self.password), verify=False, timeout=REQUEST_TIMEOUT, proxies={"http": None, "https": None})
            response.raise_for_status()
            self.log_info(f"Sensor values reset successfully. Response: {response.status_code} | {response.text}")
            return True
        except requests.RequestException as e:
            self.log_failure('Zurücksetzen', e, response, action=True)
            return False
        
    def reboot_sensor(self):
        """
        Reboot sensor
        """
        self.last_action_error = None
        url = f"https://{self.ip_address}/stw-cgi/system.cgi?msubmenu=power&action=control&Type=Restart"
        response = None
        try:
            response = self.session.post(url, auth=HTTPDigestAuth(self.username, self.password), verify=False, timeout=REQUEST_TIMEOUT, proxies={"http": None, "https": None})
            response.raise_for_status()
            self.log_info(f"Sensor rebooted successfully. Response: {response.status_code} | {response.text}")
            return True
        except requests.RequestException as e:
            self.log_failure('Neustart', e, response, action=True)
            return False

    def check_credentials(self):
        """
        Check user name and password with a read-only request

        Returns:
        tuple: (bool, str) - success and a short description
        """
        if not self.username or not self.password:
            return False, "Benutzername oder Passwort nicht hinterlegt"
        url = f"http://{self.ip_address}/stw-cgi/eventsources.cgi?msubmenu=peoplecount&action=check&Channel=0"
        try:
            # A new connection without the session, so cached authentication cannot hide a wrong password
            response = requests.get(url, auth=HTTPDigestAuth(self.username, self.password), verify=False, timeout=REQUEST_TIMEOUT, proxies={"http": None, "https": None})
        except RequestException as e:
            return False, f"Sensor nicht erreichbar ({type(e).__name__})"
        if response.status_code in (401, 403):
            return False, f"Anmeldung abgelehnt (HTTP {response.status_code})"
        if not response.ok:
            return False, f"Unerwartete Antwort (HTTP {response.status_code})"
        return True, "Anmeldung erfolgreich"
