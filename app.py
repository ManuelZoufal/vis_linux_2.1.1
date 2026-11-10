from dotenv import load_dotenv
load_dotenv()

import logging
import os
import sys
import threading
from datetime import timedelta

import urllib3
from flask import Flask, redirect, request

# Sensors use self-signed certificates (verify=False) -> suppress the warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Version of this code. Raised with every update, see "Versionen" in README.md.
# Deliberately not read from .env, so the displayed version always matches the installed files.
APP_VERSION = "2.1.9"
APP_DEBUG = os.environ.get("APP_DEBUG", "false").strip().lower() in ("1", "true", "yes")
APP_PORT = int(os.environ.get("APP_PORT", 5000))
SESSION_LIFETIME_HOURS = int(os.environ.get("SESSION_LIFETIME_HOURS", 24))
MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", 5))

logging.basicConfig(
    level=logging.DEBUG if APP_DEBUG else logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logging.info(f"[VIS-START] Version {APP_VERSION} | NO_PROXY = {os.environ.get('NO_PROXY')}")

# Without these values the app would run with publicly known defaults
missing = [name for name in ("APP_SECRET_KEY", "DEFAULT_ADMIN_PASSWORD") if not os.environ.get(name)]
if missing:
    sys.exit(f"[VIS-START] Abbruch: Umgebungsvariable(n) fehlen: {', '.join(missing)} (.env pruefen)")

if APP_DEBUG:
    logging.warning("[VIS-START] APP_DEBUG ist aktiv: Der Werkzeug-Debugger ist im Netz erreichbar. Nicht im Produktivbetrieb verwenden!")

from routes import root_bp, admin_bp, group_bp, visualize_bp, api_bp  # Import the blueprints

from src.database import init_db, db_output_thread  # Import database functions
from src.sensor import sensors, sensor_thread  # The same sensor list the API and the scheduler use
from src.scheduler import start_scheduler  # Import scheduler functions
from src.navigator import navigator_thread  # Import navigator functions
from src import thread_status
from src.helpers import refresh_session_user

app = Flask(__name__)
app.secret_key = os.environ["APP_SECRET_KEY"]
app.config.update(
    PERMANENT_SESSION_LIFETIME=timedelta(hours=SESSION_LIFETIME_HOURS),
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    MAX_CONTENT_LENGTH=MAX_UPLOAD_MB * 1024 * 1024,
)

app.register_blueprint(root_bp, url_prefix='/')
app.register_blueprint(group_bp, url_prefix='/groups')
app.register_blueprint(visualize_bp, url_prefix='/visualize')
app.register_blueprint(api_bp, url_prefix='/api')
app.register_blueprint(admin_bp, url_prefix='/admin')


@app.context_processor
def inject_version():
    return {'app_version': APP_VERSION}


# Redirect to HTTPS
@app.before_request
def redirect_to_https():
    if not request.is_secure:
        return redirect(request.url.replace("http://", "https://", 1), code=301)


# Role changes and deleted users take effect with the next request
app.before_request(refresh_session_user)


# Thread Management: Threads report their status to src.thread_status (shown live on the logs page)

def monitor_thread(target, *args):
    thread_status.bind()
    try:
        target(*args)
    except Exception as e:
        logging.exception(f"Thread {threading.current_thread().name} crashed")
        thread_status.report_ended(f"{type(e).__name__}: {e}")
    else:
        thread_status.report_ended()


def start_monitored_thread(name, label, interval, target, *args):
    thread_status.register(name, label, interval)
    thread = threading.Thread(target=monitor_thread, args=(target, *args), name=name)
    thread.daemon = True
    thread.start()
    return thread


# Main-Program
if __name__ == "__main__":
    SENSOR_INTERVAL = 7  # Intervall in Sekunden für Sensorabfragen
    DB_OUTPUT_INTERVAL = 30  # Intervall in Sekunden für Datenbankauszug
    NAVIGATOR_INTERVAL = 60  # Intervall in Sekunden für Upload zu Navigator

    init_db()

    for sensor in sensors:
        start_monitored_thread(f"SensorThread-{sensor.sensor_id}", f"Sensor {sensor.sensor_id}: {sensor.name}", SENSOR_INTERVAL, sensor_thread, sensor, SENSOR_INTERVAL)

    start_monitored_thread("DBOutputThread", "Datenbankauszug", DB_OUTPUT_INTERVAL, db_output_thread, DB_OUTPUT_INTERVAL)
    start_monitored_thread("NavigatorUploadThread", "Navigator-Upload", NAVIGATOR_INTERVAL, navigator_thread, NAVIGATOR_INTERVAL)

    # The scheduler registers and starts its own thread
    start_scheduler('config.json')

    # use_reloader stays off: the reloader runs this block in two processes (all threads twice)
    app.run(
        debug=APP_DEBUG,
        use_reloader=False,
        ssl_context=('Webserver_IP.crt', 'Webserver_IP.pem'),
        host='0.0.0.0',
        port=APP_PORT,
    )
