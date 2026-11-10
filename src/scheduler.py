import json
import time

import schedule as schedule_lib

from threading import Thread

from src.sensor import sensors
from src.navigator import upload_data_to_navigator





def load_schedule_from_config(config_path):
    """
    Load schedule from config file
    
    Args:
    config_path (str): Path to config file
    
    Returns:
    list: List of schedules
    """
    with open(config_path, 'r') as file:
        config = json.load(file)
    return config.get('schedules', [])

def execute_schedule(schedule):
    """
    Execute a schedule
    
    Args:
    schedule (dict): Schedule to execute
    """
    # print(f"Schedule called: {schedule['action']} for sensors {schedule['sensors']} !!!")
    for sensor_id in schedule['sensors']:
        sensor = next((s for s in sensors if s.sensor_id == sensor_id), None)
        if sensor:
            if schedule['action'] == 'reset':
                sensor.reset_sensor_values()
            elif schedule['action'] == 'reboot':
                sensor.reboot_sensor()
            elif schedule['action'] == 'upload':
                upload_data_to_navigator(sensor.datapoint_id, sensor.occupancy, sensor.name)

def schedule_job(schedule):
    """
    Schedule a job
    
    Args:
    schedule (dict): Schedule to execute
    Possible values for interval: daily, weekly, hourly, every_15_minutes, every_30_minutes, every_minute, every_5_minutes

    Returns:
    None
    """
    if schedule['interval'] == 'daily':
        schedule_lib.every().day.at(schedule['time']).do(execute_schedule, schedule)
    elif schedule['interval'] == 'weekly':
        day = schedule['day'].capitalize()
        getattr(schedule_lib.every(), day).at(schedule['time']).do(execute_schedule, schedule)
    elif schedule['interval'] == 'hourly':
        schedule_lib.every().hour.at(':00').do(execute_schedule, schedule)
    elif schedule['interval'] == 'every_15_minutes':
        schedule_lib.every(15).minutes.do(execute_schedule, schedule)
    elif schedule['interval'] == 'every_30_minutes':
        schedule_lib.every(30).minutes.do(execute_schedule, schedule)
    elif schedule['interval'] == 'every_minute':
        schedule_lib.every().minute.do(execute_schedule, schedule)
    elif schedule['interval'] == 'every_5_minutes':
        schedule_lib.every(5).minutes.do(execute_schedule, schedule)

def schedule_thread(config_path):
    """
    Schedule thread
    
    Args:
    config_path (str): Path to config file
    
    Returns:
    None
    """
    schedules = load_schedule_from_config(config_path)
    for schedule in schedules:
        schedule_job(schedule)
        print(f"Added schedule: {schedule}")
    while True:
        schedule_lib.run_pending()
        time.sleep(1)

def start_scheduler(config_path):
    """
    Start scheduler thread

    Args:
    config_path (str): Path to config file

    Returns:
    None
    """
    thread = Thread(target=schedule_thread, args=(config_path,))
    thread.daemon = True
    thread.start()

def add_schedule(schedule):
    """
    Add a schedule

    Args:
    schedule (dict): Schedule to add

    Returns:
    None
    """
    schedule_job(schedule)

def edit_schedule(schedule_id, new_schedule):
    """
    Edit a schedule

    Args:
    schedule_id (int): ID of the schedule to edit
    new_schedule (dict): New schedule

    Returns:
    None
    """

    # Remove the old schedule
    schedule_lib.clear(schedule_id)
    # Add the new schedule
    schedule_job(new_schedule)

def delete_schedule(schedule_id):
    """
    Delete a schedule

    Args:
    schedule_id (int): ID of the schedule to delete

    Returns:
    None
    """
    schedule_lib.clear(schedule_id)
