import logging
import time

from src.sensor_IEE import IEE
from src.sensor_AIHANWHA import AI_HANWHA
from src.config_store import load_config
from src import thread_status
from src import sensor_credentials

def load_sensors_from_config(config_path):
    """
    Load sensors from config file

    Args:
    config_path (str): Path to config file

    Returns:
    list: List of sensors
    """
    config = load_config(config_path)
    sensors = []
    for sensor_config in config['sensors']:
        if sensor_config['type'] == 'VIRTUAL':
            # Virtual sensors have no device: their occupancy is read from config.json
            continue
        credentials = {field: value for field, (value, _source) in sensor_credentials.resolve(sensor_config).items()}
        missing = [field for field, value in credentials.items() if not value]
        if missing:
            logging.warning(f"Sensor {sensor_config.get('sensor_id')}: no {' and '.join(missing)} configured (.env or config.json)")
        if sensor_config['type'] == 'IEE':
            sensor = IEE(sensor_config['sensor_id'], sensor_config['ip_address'], sensor_config['name'], sensor_config['group_id'], credentials['password'], sensor_config.get('datapoint_id'))
        elif sensor_config['type'] == 'AI_HANWHA':
            sensor = AI_HANWHA(sensor_config['sensor_id'], sensor_config['ip_address'], sensor_config['name'], sensor_config['group_id'], credentials['username'], credentials['password'], sensor_config.get('datapoint_id'))
        else:
            logging.error(f"Sensor {sensor_config.get('sensor_id')} skipped: unknown type {sensor_config['type']}")
            continue
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
            if sensor.fetch_sensor_values():
                thread_status.report_success()
            else:
                thread_status.report_error(sensor.last_error or "Abfrage fehlgeschlagen")
        except Exception as e:
            thread_status.report_error(f"{type(e).__name__}: {e}")
        time.sleep(interval)

sensors = load_sensors_from_config('config.json')
