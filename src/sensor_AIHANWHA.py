import requests

from requests.auth import HTTPDigestAuth
from requests.exceptions import ConnectionError, SSLError, Timeout, RequestException

from src.database import save_sensor_values
from src.sensor_base import Sensor

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
        self.session = requests.Session()

    def fetch_sensor_values(self):
        """
        Fetch sensor values from sensor and save to database

        Returns:
        bool: True if values fetched successfully, False
        otherwise
        """

        protocols = ["http"]
        last_exception = None

        for protocol in protocols:
            url = f"{protocol}://{self.ip_address}/stw-cgi/eventsources.cgi?msubmenu=peoplecount&action=check&Channel=0"
            try:
                response = self.session.get(url, auth=HTTPDigestAuth(self.username, self.password), verify=False, proxies={"http": None, "https": None})
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

            except (ConnectionError, SSLError, Timeout) as e:
                last_exception = e
                self.log_info(f"{protocol.upper()} request failed for sensor {self.name}. Trying fallback... Error: {e}")
                continue

            except RequestException as e:
                self.log_error(f"Request error fetching sensor values for {self.name} via {protocol.upper()}: {e}. Response: {getattr(e.response, 'text', 'No response')}")
            return False

        # Falls beide Protokolle fehlschlagen
        self.log_error(f"All attempts to fetch sensor values for {self.name} failed. Last error: {last_exception}")
        return False
        
    def reset_sensor_values(self):
        """
        Reset sensor values"
        """
        url = f"https://{self.ip_address}/stw-cgi/system.cgi?msubmenu=databasereset&action=control&IncludeDataType=PeopleCount"
        try:
            response = self.session.post(url, auth=HTTPDigestAuth(self.username, self.password), verify=False, proxies={"http": None, "https": None})
            response.raise_for_status()
            self.log_info(f"Sensor values reset successfully. Response: {response.status_code} | {response.text}")
            return True
        except requests.RequestException as e:
            self.log_error(f"Error resetting sensor values: {e}. Response: {response.text if response else 'No response'}")
            return False
        
    def reboot_sensor(self):
        """
        Reboot sensor
        """
        url = f"https://{self.ip_address}/stw-cgi/system.cgi?msubmenu=power&action=control&Type=Restart"
        try:
            response = self.session.post(url, auth=HTTPDigestAuth(self.username, self.password), verify=False, proxies={"http": None, "https": None})
            response.raise_for_status()
            self.log_info(f"Sensor rebooted successfully. Response: {response.status_code} | {response.text}")
            return True
        except requests.RequestException as e:
            self.log_error(f"Error rebooting sensor: {e}. Response: {response.text if response else 'No response'}")
            return False
        
    
