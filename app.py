from dotenv import load_dotenv
load_dotenv()

import urllib3
# Disable SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

import logging
# Setup logging

import json
import threading
import os

logging.basicConfig(level=logging.DEBUG)
logging.warning(f"[VIS-START] NO_PROXY = {os.environ.get('NO_PROXY')}")

from flask import Flask, render_template, request, session, redirect, url_for
from datetime import timedelta

from routes import root_bp, admin_bp, group_bp, visualize_bp, api_bp # Import the blueprints

from src.database import init_db, db_output_thread  # Import database functions
from src.sensor import load_sensors_from_config, sensor_thread  # Import sensor functions
from src.scheduler import start_scheduler  # Import scheduler functions
from src.navigator import upload_data_to_navigator, navigator_thread  # Import navigator functions
from src.helpers import login_required


APP_VERSION = "2.1.0"

app = Flask(__name__)
app.secret_key = os.environ.get("APP_SECRET_KEY", "your_secret_key")  # Set a secret key for session management

@app.context_processor
def inject_version():
    return {'app_version': APP_VERSION}

session_lifetime = int(os.environ.get("SESSION_LIFETIME_HOURS", 24))  # Set session lifetime
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=session_lifetime)  # Set session lifetime

app.register_blueprint(root_bp, url_prefix='/')
app.register_blueprint(group_bp, url_prefix='/groups')
app.register_blueprint(visualize_bp, url_prefix='/visualize')
app.register_blueprint(api_bp, url_prefix='/api')
app.register_blueprint(admin_bp, url_prefix='/admin')

# Load configuration
with open('config.json', 'r') as file:
    config = json.load(file)

# Global list to store thread statuses
thread_statuses = []

# Redirect to HTTPS
@app.before_request
def before_request():
    if not request.is_secure:
        url = request.url.replace("http://", "https://", 1)
        return redirect(url, code=301)
    session.permanent = True
    session.modified = True
    #print('Before request')
    #print('Endpoint: ', request.endpoint, ' | Path', request.path)

# Thread Management: Monitor threads and store their status

def monitor_thread(name, target, *args):
    try:
        target(*args)
    except Exception as e:
        thread_statuses.append({'name': name, 'status': 'error', 'error': str(e)})
    else:
        thread_statuses.append({'name': name, 'status': 'running'})

# Main-Program
if __name__ == "__main__":
    init_db()
    sensors = load_sensors_from_config('config.json')
    
    sensor_interval = 7  # Intervall in Sekunden für Sensorabfragen
    db_output_interval = 30  # Intervall in Sekunden für Datenbankauszug
    navigator_interval = 60  # Intervall in Sekunden für Upload zu Navigator

    threads = []
    for sensor in sensors:
        thread = threading.Thread(target=monitor_thread, args=(f"SensorThread-{sensor.sensor_id}", sensor_thread, sensor, sensor_interval), name=f"SensorThread-{sensor.name}")
        thread.daemon = True
        threads.append(thread)
        thread.start()

    db_thread = threading.Thread(target=monitor_thread, args=("DBOutputThread", db_output_thread, db_output_interval), name="DBOutputThread")
    db_thread.daemon = True
    threads.append(db_thread)
    db_thread.start()

    navigator_thread = threading.Thread(target=monitor_thread, args=("NavigatorUploadThread", navigator_thread, navigator_interval), name="NavigatorUploadThread")
    navigator_thread.daemon = True
    threads.append(navigator_thread)
    navigator_thread.start()

    scheduler_thread = threading.Thread(target=monitor_thread, args=("SchedulerThread", start_scheduler, 'config.json'), name="SchedulerThread")
    scheduler_thread.daemon = True
    threads.append(scheduler_thread)
    scheduler_thread.start()

    for sensor in sensors:
        upload_data_to_navigator(sensor.datapoint_id, sensor.occupancy, sensor.name)

    # Start the Flask app
    app.run(debug=True, use_reloader=True, ssl_context=('Webserver_IP.crt', 'Webserver_IP.pem'), host='0.0.0.0', port=os.environ.get("APP_PORT"), load_dotenv=True)
