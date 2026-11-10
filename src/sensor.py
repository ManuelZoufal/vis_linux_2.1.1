import json
import time

from src.sensor_IEE import IEE
from src.sensor_AIHANWHA import AI_HANWHA
from src.database import save_sensor_values

def load_sensors_from_config(config_path):
    """
    Load sensors from config file

    Args:
    config_path (str): Path to config file

    Returns:
    list: List of sensors
    """
    with open(config_path, 'r') as file:
        config = json.load(file)
    sensors = []
    for sensor_config in config['sensors']:
        if sensor_config['type'] == 'IEE':
            sensor = IEE(sensor_config['sensor_id'], sensor_config['ip_address'], sensor_config['name'], sensor_config['group_id'], sensor_config['password'], sensor_config['datapoint_id'])
        elif sensor_config['type'] == 'AI_HANWHA':
            sensor = AI_HANWHA(sensor_config['sensor_id'], sensor_config['ip_address'], sensor_config['name'], sensor_config['group_id'], sensor_config['username'], sensor_config['password'], sensor_config['datapoint_id'])
        sensors.append(sensor)
    return sensors

def sensor_thread(sensor, interval):
    """
    Sensor thread

    Args:
    sensor (Sensor): Sensor object
    interval (int): Interval in seconds

    Returns:
    None
    """
    while True:
        try:
            sensor.fetch_sensor_values()
        except:
            pass
        time.sleep(interval)

sensors = load_sensors_from_config('config.json')
