import logging
import re
import time

import schedule as schedule_lib

from threading import Thread

from src.sensor import sensors
from src.navigator import upload_data_to_navigator, has_datapoint
from src.config_store import load_config
from src import thread_status

SCHEDULER_THREAD_NAME = 'SchedulerThread'
SCHEDULER_INTERVAL = 1  # Sekunden zwischen zwei Pruefungen auf faellige Zeitplaene





def load_schedule_from_config(config_path):
    """
    Load schedule from config file
    
    Args:
    config_path (str): Path to config file
    
    Returns:
    list: List of schedules
    """
    config = load_config(config_path)
    return config.get('schedules', [])

ACTIONS = ('reset', 'reboot', 'upload')
WEEKDAYS = ('monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday')
INTERVALS = ('every_minute', 'every_5_minutes', 'every_15_minutes', 'every_30_minutes', 'hourly', 'daily', 'weekly')
TIME_PATTERN = re.compile(r'^([01]\d|2[0-3]):[0-5]\d$')


def validate_schedule(schedule, check_sensors=True):
    """
    Check a schedule before it is saved or scheduled

    Args:
    schedule (dict): Schedule to check
    check_sensors (bool): Also reject sensors that are not in config.json

    Returns:
    str: Description of the first problem, None if the schedule is valid
    """
    if schedule.get('action') not in ACTIONS:
        return f"Unbekannte Aktion: {schedule.get('action')}"
    if schedule.get('interval') not in INTERVALS:
        return f"Unbekanntes Intervall: {schedule.get('interval')}"
    if schedule['interval'] in ('daily', 'weekly'):
        if not isinstance(schedule.get('time'), str) or not TIME_PATTERN.match(schedule['time']):
            return f"Ungültige Uhrzeit (erwartet HH:MM): {schedule.get('time')}"
    if schedule['interval'] == 'weekly' and str(schedule.get('day', '')).lower() not in WEEKDAYS:
        return f"Ungültiger Wochentag: {schedule.get('day')}"
    sensor_ids = schedule.get('sensors')
    if not isinstance(sensor_ids, list) or not sensor_ids:
        return "Es muss mindestens ein Sensor ausgewählt sein"
    known = {s.sensor_id for s in sensors}
    unknown = [str(sensor_id) for sensor_id in sensor_ids if sensor_id not in known]
    if check_sensors and unknown:
        return f"Unbekannte Sensoren: {', '.join(unknown)}"
    return None


def schedule_tag(schedule_id):
    """Tag that identifies the job of a schedule in the schedule library"""
    return f"schedule-{schedule_id}"


def execute_schedule(schedule):
    """
    Execute a schedule

    A failing sensor does not stop the action for the remaining sensors.
    This function must never raise: the schedule library only plans the next
    run after the job returned, a raising job would be repeated every second.

    Args:
    schedule (dict): Schedule to execute
    """
    failed = []
    for sensor_id in schedule['sensors']:
        sensor = next((s for s in sensors if s.sensor_id == sensor_id), None)
        if not sensor:
            continue
        try:
            if schedule['action'] == 'reset':
                success = sensor.reset_sensor_values()
            elif schedule['action'] == 'reboot':
                success = sensor.reboot_sensor()
            elif schedule['action'] == 'upload':
                # A sensor without Navigator datapoint has nothing to upload
                success = (not has_datapoint(sensor.datapoint_id)
                           or upload_data_to_navigator(sensor.datapoint_id, sensor.occupancy, sensor.name))
            else:
                success = False
        except Exception as e:
            logging.error(f"Schedule {schedule.get('id')}: {schedule['action']} failed for sensor {sensor.name}: {e}")
            success = False
        if not success:
            failed.append(sensor.name)
    if failed:
        message = f"Zeitplan {schedule.get('id')} ({schedule['action']}): fehlgeschlagen für {', '.join(failed)}"
        logging.error(message)
        thread_status.report_error(message)


def schedule_job(schedule):
    """
    Schedule a job

    Args:
    schedule (dict): Schedule to execute
    Possible values for interval: daily, weekly, hourly, every_15_minutes, every_30_minutes, every_minute, every_5_minutes

    The job is tagged with the schedule id, so it can be removed again.

    Returns:
    None
    """
    interval = schedule['interval']
    if interval == 'daily':
        job = schedule_lib.every().day.at(schedule['time'])
    elif interval == 'weekly':
        job = getattr(schedule_lib.every(), schedule['day'].lower()).at(schedule['time'])
    elif interval == 'hourly':
        job = schedule_lib.every().hour.at(':00')
    elif interval == 'every_15_minutes':
        job = schedule_lib.every(15).minutes
    elif interval == 'every_30_minutes':
        job = schedule_lib.every(30).minutes
    elif interval == 'every_minute':
        job = schedule_lib.every().minute
    elif interval == 'every_5_minutes':
        job = schedule_lib.every(5).minutes
    else:
        raise ValueError(f"Unknown interval: {interval}")
    job.do(execute_schedule, schedule).tag(schedule_tag(schedule['id']))

def schedule_thread(config_path):
    """
    Schedule thread
    
    Args:
    config_path (str): Path to config file
    
    Returns:
    None
    """
    thread_status.bind()
    try:
        schedules = load_schedule_from_config(config_path)
        for schedule in schedules:
            # Unknown sensors are tolerated here, they are skipped when the schedule runs
            problem = validate_schedule(schedule, check_sensors=False)
            if problem:
                logging.error(f"Schedule {schedule.get('id')} from config skipped: {problem}")
                continue
            schedule_job(schedule)
            logging.info(f"Added schedule: {schedule}")
        while True:
            # A failing job must not end the thread, otherwise all schedules stop
            try:
                schedule_lib.run_pending()
                thread_status.report_success(f"{len(schedule_lib.get_jobs())} Zeitpläne aktiv")
            except Exception as e:
                thread_status.report_error(f"{type(e).__name__}: {e}")
            time.sleep(SCHEDULER_INTERVAL)
    except Exception as e:
        thread_status.report_ended(f"{type(e).__name__}: {e}")
        raise

def start_scheduler(config_path):
    """
    Start scheduler thread

    Args:
    config_path (str): Path to config file

    Returns:
    None
    """
    thread_status.register(SCHEDULER_THREAD_NAME, 'Scheduler (geplante Aktionen)', SCHEDULER_INTERVAL)
    thread = Thread(target=schedule_thread, args=(config_path,), name=SCHEDULER_THREAD_NAME)
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
    new_schedule (dict): Complete new schedule (including its id)

    Returns:
    None
    """
    # Remove the old job and add the new one
    schedule_lib.clear(schedule_tag(schedule_id))
    schedule_job(new_schedule)

def delete_schedule(schedule_id):
    """
    Delete a schedule

    Args:
    schedule_id (int): ID of the schedule to delete

    Returns:
    None
    """
    schedule_lib.clear(schedule_tag(schedule_id))
