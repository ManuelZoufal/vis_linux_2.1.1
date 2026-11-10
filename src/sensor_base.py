import logging


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

    def log_info(self, message):
        """
        Log info message

        Args:
        message (str): Message to log
        """
        logging.info(f"{self.name}: {message}")

    def log_error(self, message):
        """
        Log error message

        Args:
        message (str): Message to log
        """
        logging.error(f"{self.name}: {message}")

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

    
