from . import api_bp

from src.sensor import sensors
from src.helpers import get_local_ip, log_change, api_login_required
from src.scheduler import add_schedule as scheduler_add_schedule, edit_schedule as scheduler_edit_schedule, delete_schedule as scheduler_delete_schedule, validate_schedule
from src.database import get_connection, save_sensor_values, delete_sensor_values
from src.config_store import load_config, save_config, with_config_lock
from src import thread_status
from src import certificate
from src import event_log

from flask import jsonify, session, request, send_file, current_app
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
import logging
import socket
import io
import os



def _display_timezone():
    """
    Timezone for timestamps shown in the user interface (APP_TIMEZONE, default Europe/Berlin).
    Follows daylight saving time. Falls back to fixed UTC+1 if the timezone is unknown.
    """
    name = os.environ.get('APP_TIMEZONE', 'Europe/Berlin')
    try:
        return ZoneInfo(name)
    except Exception as e:
        logging.warning(f"Timezone {name} not available ({e}), using fixed UTC+1")
        return timezone(timedelta(hours=1))


DISPLAY_TIMEZONE = _display_timezone()


def _group_values(data, current=None):
    """
    Read and check the settings of a group from request data

    Args:
    data (dict): Request data
    current (dict, optional): Existing group, its values are kept for fields missing in data

    Returns:
    tuple: (values, None) or (None, description of the problem)
    """
    current = current or {}
    name = str(data.get('name', current.get('name', '')) or '').strip()
    if not name:
        return None, 'Der Name darf nicht leer sein'
    try:
        max_occupancy = int(data.get('max_occupancy', current.get('max_occupancy')))
    except (TypeError, ValueError):
        return None, 'Die maximale Belegung muss eine ganze Zahl sein'
    if max_occupancy < 0:
        return None, 'Die maximale Belegung darf nicht negativ sein'
    maintenance_mode = data.get('maintenance_mode', current.get('maintenance_mode', False))
    if not isinstance(maintenance_mode, bool):
        return None, 'Der Wartungsmodus muss true oder false sein'
    welcome_text = str(data.get('welcome_text', current.get('welcome_text', '')) or '')
    return {'name': name, 'max_occupancy': max_occupancy, 'welcome_text': welcome_text,
            'maintenance_mode': maintenance_mode}, None


def _remove_display_images(group):
    """Delete the display image files of a group from the upload folder"""
    upload_folder = _upload_folder()
    for filename in group.get('display_images') or []:
        if not filename:
            continue
        path = os.path.join(upload_folder, os.path.basename(filename))  # never leave the upload folder
        if os.path.isfile(path):
            os.remove(path)


def _virtual_sensor_values(data, current=None):
    """
    Read name, group and occupancy of a virtual sensor from request data

    Returns:
    tuple: (values, None) or (None, description of the problem)
    """
    current = current or {}
    name = str(data.get('name', current.get('name', ''))).strip()
    if not name:
        return None, 'Der Name darf nicht leer sein'
    group_id = str(data.get('group_id', current.get('group_id', '')))
    try:
        occupancy = int(data.get('occupancy', current.get('occupancy', 0)))
    except (TypeError, ValueError):
        return None, 'Die Belegung muss eine ganze Zahl sein'
    return {'name': name, 'group_id': group_id, 'occupancy': occupancy}, None


# /api
@api_bp.route('/')
def api_index():
    """
    API index route
    ---
    get:
      description: Returns a JSON object with a status message
      responses:
        200:
          description: API is running
          content:
            application/json:
              schema:
                type: object
                properties:
                  status:
                    type: string
                    description: The status of the API
                    example: success
                  message:
                    type: string
                    description: A message from the API
                    example: API is running
    """
    return jsonify({'status': 'success', 'message': 'API is running'}), 200

# /api/get_data
@api_bp.route('/get_data')
def get_data():
    """
    Get sensor data
    ---
    get:
      description: Returns a JSON object with sensor data
      responses:
        200:
          description: Sensor data
          content:
            application/json:
              schema:
                type: object
                properties:
                  local_ip:
                    type: string
                    description: The local IP address
                    example:
                  server_hostname:
                    type: string
                    description: The server hostname
                    example:
                  system_time:
                    type: string
                    description: The system time
                    example:
                  sensors:
                    type: array
                    description: An array of sensor data
                    items:
                      type: object
                      properties:
                        sensor_id:
                          type: integer
                          description: The sensor ID
                          example: 1
                        name:
                          type: string
                          description: The sensor name
                          example: Sensor 1
                        ip_address:
                          type: string
                          description: The sensor IP address
                          example:
                        group_id:
                          type: integer
                          description: The group ID
                          example: 1
                        occupancy:
                          type: integer
                          description: The sensor occupancy
                          example: 0
                        forward_value:
                          type: integer
                          description: The forward value
                          example: 0
                        backward_value:
                          type: integer
                          description: The backward value
                          example: 0
                        timestamp:
                          type: string
                          description: The sensor timestamp
                          example:
                        type:
                          type: string
                          description: The sensor type
                          example: motion
                  groups:
                    type: array
                    description: An array of group data
                    items:
                      type: object
                      properties:
                        group_id:
                          type: integer
                          description: The group ID
                          example: 1
                        name:
                          type: string
                          description: The group name
                          example: Group 1
    """
    # Get the local IP address, server hostname, and system time
    local_ip = get_local_ip()
    server_hostname = socket.gethostname()
    system_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    # Get sensor data from the database
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT sensor_id, group_id, occupancy, forward_value, backward_value, datapoint_id, timestamp FROM sensor_data')
    db_data = cursor.fetchall()
    conn.close()

    # Get sensor data from the config file
    config = load_config()
    
    # Combine sensor data from the config file and the database
    sensor_data = [{
        'sensor_id': sensor['sensor_id'],
        'name': sensor['name'],
        'ip_address': sensor.get('ip_address', 'N/A'),
        'group_id': sensor['group_id'],
        'occupancy': next((row[2] for row in db_data if row[0] == sensor['sensor_id']), sensor.get('occupancy', 0)),
        'forward_value': next((row[3] for row in db_data if row[0] == sensor['sensor_id']), 0),
        'backward_value': next((row[4] for row in db_data if row[0] == sensor['sensor_id']), 0),
        'datapoint_id': sensor.get('datapoint_id') or 'N/A',
        'timestamp': next((row[6] for row in db_data if row[0] == sensor['sensor_id']), 'N/A'),
        'type': sensor['type'],
        'counting': sensor.get('counting', True) is not False
    } for sensor in config['sensors']]

    # Convert timestamps to the desired timezone
    for sensor in sensor_data:
        if sensor['timestamp'] != 'N/A':
            dt = datetime.strptime(sensor['timestamp'], '%Y-%m-%d %H:%M:%S')
            dt = dt.replace(tzinfo=timezone.utc).astimezone(DISPLAY_TIMEZONE)  # The database stores UTC
            sensor['timestamp'] = dt.strftime('%Y-%m-%d %H:%M:%S %Z')
    # Get group data from the config file
    group_data = config['groups']

    # Return the sensor data and group data as a JSON object
    return jsonify({
        'local_ip': local_ip,
        'server_hostname': server_hostname,
        'system_time': system_time,
        'sensors': sensor_data,
        'groups': group_data
    }), 200

# /api/logs
@api_bp.route('/logs')
@api_login_required()
def get_logs():
    """
    Get logs
    ---
    get:
      description: Returns a JSON object with logs
      responses:
        200:
          description: Logs
          content:
            application/json:
              schema:
                type: object
                properties:
                  logs:
                    type: array
                    description: An array of log messages
                    items:
                      type: string
                      example: Log message 1
        500:
          description: Internal server error
          content:
            application/json:
              schema:
                type: object
                properties:
                  error:
                    type: string
                    example: Error message
    """
    # Only the newest entries are read, from the end of the file, so the request
    # stays fast however large the change log has become
    try:
        limit = max(1, min(int(request.args.get('limit', 500)), 5000))
    except ValueError:
        limit = 500
    logs = []
    truncated = False
    try:
        if os.path.exists('change_log.txt'):
            for line in event_log.lines_backwards('change_log.txt'):
                if ' - ' not in line:
                    continue  # skip empty or damaged lines instead of failing the whole request
                if len(logs) >= limit:
                    truncated = True
                    break
                timestamp, message = line.strip().split(' - ', 1)
                logs.append({'timestamp': timestamp, 'message': message})
        return jsonify({'logs': logs, 'truncated': truncated, 'limit': limit}), 200
    # Handle exceptions
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# /api/thread_status
@api_bp.route('/thread_status')
def get_thread_status():
    """
    Get the live status of the background threads
    ---
    get:
      description: Returns one entry per background thread (sensor polling, Navigator upload, scheduler, database output)
      responses:
        200:
          description: Thread status retrieved successfully
          content:
            application/json:
              schema:
                type: object
                properties:
                  server_time:
                    type: string
                    example: 2023-01-01 12:00:00
                  threads:
                    type: array
                    items:
                      type: object
                      properties:
                        name:
                          type: string
                          example: SensorThread-1
                        label:
                          type: string
                          example: "Sensor 1: Eingang"
                        state:
                          type: string
                          description: ok, error, stale (no report for too long), starting, stopped or not_started
                          example: ok
                        last_success:
                          type: string
                          example: 2023-01-01 12:00:00
                        last_error:
                          type: string
                          example: Abfrage fehlgeschlagen
                        last_error_time:
                          type: string
                          example: 2023-01-01 11:59:00
                        run_count:
                          type: integer
                          example: 120
                        error_count:
                          type: integer
                          example: 2
        403:
          description: Unauthorized to view thread status
    """
    if 'role' in session and session['role'] == 'Administrator':
        return jsonify({
            'server_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'threads': thread_status.snapshot(),
            'certificate': certificate.get_status()
        }), 200
    return jsonify({'error': 'Unauthorized to view thread status'}), 403

THREAD_STATE_LABELS = {
    'ok': 'OK',
    'error': 'Fehler',
    'stale': 'Keine Rückmeldung',
    'idle': 'Keine Zählung',
    'starting': 'Startet',
    'stopped': 'Beendet',
    'not_started': 'Nicht gestartet',
}


# /api/thread_status/export
@api_bp.route('/thread_status/export')
def export_thread_status():
    """
    Export the status of the background threads
    ---
    get:
      description: Returns the current thread status as a text file download
      responses:
        200:
          description: Thread status exported successfully
          content:
            text/plain:
              schema:
                type: string
                format: binary
        403:
          description: Unauthorized to export thread status
    """
    if not ('role' in session and session['role'] == 'Administrator'):
        return jsonify({'error': 'Unauthorized to export thread status'}), 403

    now = datetime.now()
    threads = thread_status.snapshot()
    ok_count = sum(1 for thread in threads if thread['state'] == 'ok')
    idle_count = sum(1 for thread in threads if thread['state'] == 'idle')
    lines = [
        'VIS Thread-Status',
        f"Erstellt:  {now.strftime('%Y-%m-%d %H:%M:%S')}",
        f"Version:   {current_app.config.get('APP_VERSION', 'unbekannt')}",
        f"Server:    {socket.gethostname()}",
        f"Übersicht: {ok_count} von {len(threads) - idle_count} Threads OK" + (f", {idle_count} ohne Zählung" if idle_count else ""),
        f"TLS:       {certificate.get_status()['message']}",
        '',
    ]
    for thread in threads:
        state = THREAD_STATE_LABELS.get(thread['state'], thread['state'])
        lines.append(f"[{state}] {thread['label']}")
        lines.append(f"    Thread-Name:     {thread['name']}")
        lines.append(f"    Intervall:       {thread['interval']} s")
        lines.append(f"    Gestartet:       {thread['started_at'] or '-'}")
        lines.append(f"    Letzter Erfolg:  {thread['last_success'] or '-'}")
        lines.append(f"    Durchläufe:      {thread['run_count']} (davon Fehler: {thread['error_count']})")
        if thread['detail']:
            lines.append(f"    Letzte Meldung:  {thread['detail']}")
        if thread['last_error']:
            lines.append(f"    Letzter Fehler:  {thread['last_error_time']}")
            lines.append(f"                     {thread['last_error']}")
        lines.append('')

    content = io.BytesIO('\r\n'.join(lines).encode('utf-8'))
    return send_file(content, as_attachment=True, mimetype='text/plain; charset=utf-8',
                     download_name=f"thread_status_{now.strftime('%Y%m%d_%H%M%S')}.txt")

EVENT_KIND_LABELS = {
    'error': 'Fehler',
    'ongoing': 'Fehler dauert an',
    'recovered': 'Wieder OK',
    'ended': 'Thread beendet',
    'schedule': 'Zeitplan',
    'navigator': 'Navigator',
    'detail': 'Detail-Protokoll',
    'start': 'Start',
    'info': 'Hinweis',
}
DETAIL_MINUTES = (15, 60, 360, 1440)


def _is_admin():
    return 'role' in session and session['role'] == 'Administrator'


def _event_filter():
    """Read the filter of the event log from the query string: (hours or None, source or None)"""
    try:
        hours = float(request.args.get('hours', 24))
    except ValueError:
        hours = 24
    return (hours if hours > 0 else None), (request.args.get('source') or None)


# /api/events
@api_bp.route('/events')
def get_events():
    """
    Get the event log
    ---
    get:
      description: Failures, recoveries and executed schedules, newest first
      parameters:
        - name: hours
          in: query
          description: Only events of the last hours (0 for all), default 24
        - name: source
          in: query
          description: Only events of this thread, e.g. SensorThread-5
      responses:
        200:
          description: Events retrieved successfully
        403:
          description: Unauthorized to view the event log
    """
    if not _is_admin():
        return jsonify({'error': 'Unauthorized to view the event log'}), 403
    hours, source = _event_filter()
    events, truncated = event_log.read_events(hours, source)
    for entry in events:
        entry['kind_label'] = EVENT_KIND_LABELS.get(entry.get('kind'), entry.get('kind'))
    sources = [{'name': t['name'], 'label': t['label']} for t in thread_status.snapshot()]
    return jsonify({'events': events, 'truncated': truncated, 'sources': sources}), 200


# /api/events/export
@api_bp.route('/events/export')
def export_events():
    """
    Export the event log
    ---
    get:
      description: Returns the filtered event log as a text file download, oldest first
      responses:
        200:
          description: Event log exported successfully
        403:
          description: Unauthorized to export the event log
    """
    if not _is_admin():
        return jsonify({'error': 'Unauthorized to export the event log'}), 403
    hours, source = _event_filter()
    events, truncated = event_log.read_events(hours, source, limit=100000)
    now = datetime.now()
    lines = [
        'VIS Ereignisprotokoll',
        f"Erstellt:  {now.strftime('%Y-%m-%d %H:%M:%S')}",
        f"Version:   {current_app.config.get('APP_VERSION', 'unbekannt')}",
        f"Zeitraum:  {'letzte ' + format(hours, 'g') + ' Stunden' if hours else 'alles'}",
        f"Quelle:    {source or 'alle'}",
        f"Einträge:  {len(events)}{' (gekürzt)' if truncated else ''}",
        '',
    ]
    for entry in reversed(events):
        kind = EVENT_KIND_LABELS.get(entry.get('kind'), entry.get('kind'))
        lines.append(f"{entry.get('ts')} | {kind} | {entry.get('label')} | {entry.get('message')}")
    content = io.BytesIO('\r\n'.join(lines).encode('utf-8'))
    return send_file(content, as_attachment=True, mimetype='text/plain; charset=utf-8',
                     download_name=f"ereignisse_{now.strftime('%Y%m%d_%H%M%S')}.txt")


# /api/detail_log
@api_bp.route('/detail_log')
def get_detail_log():
    """
    Get the state of the detail log and the list of its files
    ---
    get:
      responses:
        200:
          description: State retrieved successfully
        403:
          description: Unauthorized
    """
    if not _is_admin():
        return jsonify({'error': 'Unauthorized to view the detail log'}), 403
    return jsonify(event_log.detail_status()), 200


# /api/detail_log/start
@api_bp.route('/detail_log/start', methods=['POST'])
def start_detail_log():
    """
    Switch the detail log on for a limited time
    ---
    post:
      description: Records every request to the sensors and to Navigator until the time is over or the size limit is reached
      requestBody:
        content:
          application/json:
            schema:
              type: object
              properties:
                minutes:
                  type: integer
                  description: 15, 60, 360 or 1440
                scope:
                  type: string
                  description: all, sensors, navigator, scheduler or sensor:<id>
      responses:
        200:
          description: Detail log started
        400:
          description: Invalid duration or scope
        403:
          description: Unauthorized
    """
    if not _is_admin():
        return jsonify({'error': 'Unauthorized to start the detail log'}), 403
    data = request.get_json(silent=True) or {}
    minutes = data.get('minutes')
    scope = str(data.get('scope', 'all'))
    if minutes not in DETAIL_MINUTES:
        return jsonify({'status': 'error', 'message': 'Ungültige Dauer'}), 400
    sensor_ids = {s.sensor_id for s in sensors}
    if scope not in ('all', 'sensors', 'navigator', 'scheduler') and not (scope.startswith('sensor:') and scope[7:] in sensor_ids):
        return jsonify({'status': 'error', 'message': 'Ungültiger Umfang'}), 400
    try:
        name = event_log.start_detail(minutes, scope)
    except OSError as e:
        return jsonify({'status': 'error', 'message': f'Detail-Protokoll konnte nicht gestartet werden: {e}'}), 500
    log_change(f"Detail log started for {minutes} minutes, scope {scope}, by user id {session.get('user_id')}")
    return jsonify({'status': 'success', 'file': name}), 200


# /api/detail_log/stop
@api_bp.route('/detail_log/stop', methods=['POST'])
def stop_detail_log():
    """
    Switch the detail log off
    ---
    post:
      responses:
        200:
          description: Detail log stopped (or was not running)
        403:
          description: Unauthorized
    """
    if not _is_admin():
        return jsonify({'error': 'Unauthorized to stop the detail log'}), 403
    return jsonify({'status': 'success', 'file': event_log.stop_detail()}), 200


# /api/detail_log/files/<name>
@api_bp.route('/detail_log/files/<name>', methods=['GET', 'DELETE'])
def detail_log_file(name):
    """
    Download or delete a detail log file
    ---
    get:
      responses:
        200:
          description: File download
        404:
          description: File not found
    delete:
      responses:
        200:
          description: File deleted
        400:
          description: The file is being written and cannot be deleted
    """
    if not _is_admin():
        return jsonify({'error': 'Unauthorized to access detail log files'}), 403
    path = event_log.detail_file_path(name)
    if not path:
        return jsonify({'status': 'error', 'message': 'Datei nicht gefunden'}), 404
    if request.method == 'DELETE':
        if not event_log.delete_detail_file(name):
            return jsonify({'status': 'error', 'message': 'Die Datei wird gerade geschrieben'}), 400
        return jsonify({'status': 'success'}), 200
    return send_file(os.path.abspath(path), as_attachment=True, mimetype='text/plain; charset=utf-8', download_name=name)


# /api/export_logs
@api_bp.route('/logs/export')
def export_logs():
    """
    Export logs
    ---
    get:
      description: Returns a file download of the logs
      responses:
        200:
          description: File download
          content:
            application/octet-stream:
              schema:
                type: file
        403:
          description: Unauthorized
          content:
            application/json:
              schema:
                type: object
                properties:
                  error:
                    type: string
                    example: Unauthorized
    """
    # Check if the user is an administrator
    if 'role' in session and session['role'] == 'Administrator':
        # Return the change_log.txt file as an attachment
        return send_file('change_log.txt', as_attachment=True)
    return jsonify({'error': 'Unauthorized to export logs'}), 403

# /api/sensors/<sensor_id>/reset
@api_bp.route('/sensors/<sensor_id>/reset', methods=['POST'])
@api_login_required(role='Administrator')
def reset_sensor(sensor_id):
    """
    Reset sensor
    ---
    post:
      description: Resets a sensors count values
      parameters:
        - in: path
          name: sensor_id
          schema:
            type: integer
          required: true
          description: The ID of the sensor to reset
      responses:
        200:
          description: Sensor reset
          content:
            application/json:
              schema:
                type: object
                properties:
                  status:
                    type: string
                    description: The status of the reset operation
                    example: success
        404:
          description: Sensor not found
          content:
            application/json:
              schema:
                type: object
                properties:
                  status:
                    type: string
                    example: error
                  message:
                    type: string
                    example: Sensor not found
    """
    sensor = next((s for s in sensors if s.sensor_id == sensor_id), None)
    if not sensor:
        return jsonify({'status': 'error', 'message': 'Sensor not found'}), 404
    if not sensor.counting:
        return jsonify({'status': 'error', 'message': 'Dieser Sensor wird nicht für die Zählung verwendet'}), 400
    if sensor.reset_sensor_values():
        log_change(f"Sensor {sensor_id} reset")
        return jsonify({'status': 'success'}), 200
    return jsonify({'status': 'error', 'message': sensor.last_action_error or 'Zurücksetzen fehlgeschlagen'}), 502

# /api/sensors/<sensor_id>/reboot
@api_bp.route('/sensors/<sensor_id>/reboot', methods=['POST'])
@api_login_required(role='Administrator')
def reboot_sensor(sensor_id):
    """
    Reboot sensor
    ---
    post:
      description: Reboots a sensor
      parameters:
        - in: path
          name: sensor_id
          schema:
            type: integer
          required: true
          description: The ID of the sensor to reboot
      responses:
        200:
          description: Sensor rebooted
          content:
            application/json:
              schema:
                type: object
                properties:
                  status:
                    type: string
                    description: The status of the reboot operation
                    example: success
        404:
          description: Sensor not found
          content:
            application/json:
              schema:
                type: object
                properties:
                  status:
                    type: string
                    example: error
                  message:
                    type: string
                    example: Sensor not found
    """
    sensor = next((s for s in sensors if s.sensor_id == sensor_id), None)
    if not sensor:
        return jsonify({'status': 'error', 'message': 'Sensor not found'}), 404
    if sensor.reboot_sensor():
        log_change(f"Sensor {sensor_id} rebooted")
        return jsonify({'status': 'success'}), 200
    return jsonify({'status': 'error', 'message': sensor.last_action_error or 'Neustart fehlgeschlagen'}), 502

# /api/sensors/<sensor_id>/edit
@api_bp.route('/sensors/<sensor_id>/edit', methods=['POST'])
@api_login_required(role='Administrator')
@with_config_lock
def edit_sensor(sensor_id):
    """
    Edit sensor
    ---
    post:
      description: Edits a sensor's name and group ID
      parameters:
        - in: path
          name: sensor_id
          schema:
            type: integer
          required: true
          description: The ID of the sensor to edit
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              properties:
                name:
                  type: string
                  description: The new name of the sensor
                  example: Sensor 1
                group_id:
                  type: integer
                  description: The new group ID of the sensor
                  example: 1
      responses:
        200:
          description: Sensor edited
          content:
            application/json:
              schema:
                type: object
                properties:
                  status:
                    type: string
                    description: The status of the edit operation
                    example: success
        404:
          description: Sensor not found
          content:
            application/json:
              schema:
                type: object
                properties:
                  status:
                    type: string
                    example: error
                  message:
                    type: string
                    example: Sensor not found
    """
    sensor = next((s for s in sensors if s.sensor_id == sensor_id), None)
    if not sensor:
        return jsonify({'status': 'error', 'message': 'Sensor not found'}), 404

    data = request.get_json(silent=True) or {}
    config = load_config()
    name = str(data.get('name', sensor.name) or '').strip()
    if not name:
        return jsonify({'status': 'error', 'message': 'Der Name darf nicht leer sein'}), 400
    group_id = str(data.get('group_id', sensor.group_id))
    if not any(str(g['group_id']) == group_id for g in config['groups']):
        return jsonify({'status': 'error', 'message': 'Gruppe nicht gefunden'}), 400
    datapoint_id = str(data.get('datapoint_id', sensor.datapoint_id) or '').strip()
    if datapoint_id.upper() == 'N/A':
        datapoint_id = ''  # "N/A" is what the user interface shows for a missing datapoint
    counting = data.get('counting', sensor.counting)
    if not isinstance(counting, bool):
        return jsonify({'status': 'error', 'message': 'Zählung aktiv muss true oder false sein'}), 400

    # Only now change the sensor object, so a rejected request leaves it untouched
    sensor.name = name
    sensor.group_id = group_id
    sensor.datapoint_id = datapoint_id
    counting_changed = counting != sensor.counting
    sensor.counting = counting
    for sensor_config in config['sensors']:
        if sensor_config['sensor_id'] == sensor_id:
            sensor_config['name'] = name
            sensor_config['group_id'] = group_id
            sensor_config['datapoint_id'] = datapoint_id
            sensor_config['counting'] = counting
            break
    save_config(config)
    log_change(f"Sensor {sensor_id} edited: name={sensor.name}, group_id={sensor.group_id}, datapoint_id={sensor.datapoint_id}, counting={sensor.counting}")
    if counting:
        save_sensor_values(sensor)
    else:
        # Without counting the sensor has no values: it neither counts towards its group nor is it uploaded
        sensor.forward_value = sensor.backward_value = sensor.occupancy = 0
        delete_sensor_values(sensor_id)
    if counting_changed:
        event_log.event('info', f"SensorThread-{sensor_id}",
                        "Zählung aktiviert" if counting else "Zählung deaktiviert: keine Abfrage, kein Zurücksetzen, kein Upload zu Navigator",
                        f"Sensor {sensor_id}: {name}")
    return jsonify({'status': 'success'}), 200

# /api/sensors/virtual/add
@api_bp.route('/sensors/virtual/add', methods=['PUT'])
@api_login_required(role='Administrator')
@with_config_lock
def add_virtual_sensor():
    """
    Add virtual sensor
    ---
    post:
      description: Adds a virtual sensor
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              properties:
                name:
                  type: string
                  description: The name of the virtual sensor
                  example: Virtual Sensor 1
                group_id:
                  type: integer
                  description: The group ID of the virtual sensor
                  example: 1
                occupancy:
                  type: integer
                  description: The occupancy of the virtual sensor
                  example: 0
      responses:
        200:
          description: Virtual sensor added
          content:
            application/json:
              schema:
                type: object
                properties:
                  status:
                    type: string
                    description: The status of the add operation
                    example: success
                  sensor:
                    type: object
                    description: The added virtual sensor
                    properties:
                      sensor_id:
                        type: integer
                        example: 1
                      type:
                        type: string
                        example: VIRTUAL
                      name:
                        type: string
                        example: Virtual Sensor 1
                      group_id:
                        type: integer
                        example: 1
                      occupancy:
                        type: integer
                        example: 0
        500:
          description: Internal server error
          content:
            application/json:
              schema:
                type: object
                properties:
                  error:
                    type: string
                    example: Error message
    """
    values, problem = _virtual_sensor_values(request.get_json(silent=True) or {})
    if problem:
        return jsonify({'status': 'error', 'message': problem}), 400
    config = load_config()
    if not any(str(g['group_id']) == values['group_id'] for g in config['groups']):
        return jsonify({'status': 'error', 'message': 'Gruppe nicht gefunden'}), 400

    # Find the next available integer for sensor_id
    existing_sensor_ids = [int(sensor['sensor_id']) for sensor in config['sensors']]
    next_sensor_id = max(existing_sensor_ids) + 1 if existing_sensor_ids else 1

    new_sensor = {
        "sensor_id": str(next_sensor_id),  # Use the next available integer
        "type": "VIRTUAL",
        **values
    }
    config['sensors'].append(new_sensor)
    save_config(config)
    log_change(f"Virtual sensor {new_sensor['sensor_id']} added: name={new_sensor['name']}, group_id={new_sensor['group_id']}, occupancy={new_sensor['occupancy']}")
    return jsonify({'status': 'success', 'sensor': new_sensor}), 200

# /api/sensors/virtual/<sensor_id>/edit
@api_bp.route('/sensors/virtual/<sensor_id>/edit', methods=['POST'])
@api_login_required(role='Administrator')
@with_config_lock
def edit_virtual_sensor(sensor_id):
    """
    Edit virtual sensor
    ---
    post:
      description: Edits a virtual sensor's name, group ID, and occupancy
      parameters:
        - in: path
          name: sensor_id
          schema:
            type: integer
          required: true
          description: The ID of the virtual sensor to edit
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              properties:
                name:
                  type: string
                  description: The new name of the virtual sensor
                  example: Virtual Sensor 1
                group_id:
                  type: integer
                  description: The new group ID of the virtual sensor
                  example: 1
                occupancy:
                  type: integer
                  description: The new occupancy of the virtual sensor
                  example: 0
      responses:
        200:
          description: Virtual sensor edited
          content:
            application/json:
              schema:
                type: object
                properties:
                  status:
                    type: string
                    description: The status of the edit operation
                    example: success
                  sensor:
                    type: object
                    description: The edited virtual sensor
                    properties:
                      sensor_id:
                        type: integer
                        example: 1
                      type:
                        type: string
                        example: VIRTUAL
                      name:
                        type: string
                        example: Virtual Sensor 1
                      group_id:
                        type: integer
                        example: 1
                      occupancy:
                        type: integer
                        example: 0
        404:
          description: Sensor not found or not virtual
          content:
            application/json:
              schema:
                type: object
                properties:
                  status:
                    type: string
                    example: error
                  message:
                    type: string
                    example: Sensor not found or not virtual
    """
    config = load_config()
    sensor = next((s for s in config['sensors'] if s['sensor_id'] == sensor_id), None)
    if not sensor or sensor['type'] != 'VIRTUAL':
        return jsonify({'status': 'error', 'message': 'Sensor not found or not virtual'}), 404

    values, problem = _virtual_sensor_values(request.get_json(silent=True) or {}, sensor)
    if problem:
        return jsonify({'status': 'error', 'message': problem}), 400
    if not any(str(g['group_id']) == values['group_id'] for g in config['groups']):
        return jsonify({'status': 'error', 'message': 'Gruppe nicht gefunden'}), 400

    sensor.update(values)
    save_config(config)
    log_change(f"Virtual sensor {sensor_id} edited: name={sensor['name']}, group_id={sensor['group_id']}, occupancy={sensor['occupancy']}")
    return jsonify({'status': 'success', 'sensor': sensor}), 200

# /api/sensors/virtual/<sensor_id>/delete 
@api_bp.route('/sensors/virtual/<sensor_id>/delete', methods=['DELETE'])
@api_login_required(role='Administrator')
@with_config_lock
def delete_virtual_sensor(sensor_id):
    """
    Delete virtual sensor
    ---
    delete:
      description: Deletes a virtual sensor
      parameters:
        - in: path
          name: sensor_id
          schema:
            type: integer
          required: true
          description: The ID of the virtual sensor to delete
      responses:
        200:
          description: Virtual sensor deleted
          content:
            application/json:
              schema:
                type: object
                properties:
                  status:
                    type: string
                    description: The status of the delete operation
                    example: success
        404:
          description: Sensor not found or not virtual
          content:
            application/json:
              schema:
                type: object
                properties:
                  status:
                    type: string
                    example: error
                  message:
                    type: string
                    example: Sensor not found or not virtual
    """
    config = load_config()
    sensor = next((s for s in config['sensors'] if s['sensor_id'] == sensor_id), None)
    if sensor and sensor['type'] == 'VIRTUAL':
        config['sensors'] = [s for s in config['sensors'] if s['sensor_id'] != sensor_id]
        save_config(config)
        log_change(f"Virtual sensor {sensor_id} deleted")
        return jsonify({'status': 'success'}), 200
    return jsonify({'status': 'error', 'message': 'Sensor not found or not virtual'}), 404

# /api/groups/add
@api_bp.route('/groups/add', methods=['PUT'])
@api_login_required(role='Administrator')
@with_config_lock
def add_group():
    """
    Add group
    ---
    put:
      description: Adds a group
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              properties:
                name:
                  type: string
                  description: The name of the group
                  example: Group 1
                max_occupancy:
                  type: integer
                  description: The maximum occupancy of the group
                  example: 10
                welcome_text:
                  type: string
                  description: The welcome text of the group
                  example: Welcome to Group 1
                maintenance_mode:
                  type: boolean
                  description: The maintenance mode status of the group
                  example: false
      responses:
        200:
          description: Group added
          content:
            application/json:
              schema:
                type: object
                properties:
                  status:
                    type: string
                    description: The status of the add operation
                    example: success
                  group:
                    type: object
                    description: The added group
                    properties:
                      group_id:
                        type: integer
                        example: 1
                      name:
                        type: string
                        example: Group 1
                      max_occupancy:
                        type: integer
                        example: 10
                      welcome_text:
                        type: string
                        example: Welcome to Group 1
                      maintenance_mode:
                        type: boolean
                        example: false
        500:
          description: Internal server error
          content:
            application/json:
              schema:
                type: object
                properties:
                  error:
                    type: string
                    example: Error message
    """
    values, problem = _group_values(request.get_json(silent=True) or {})
    if problem:
        return jsonify({'status': 'error', 'message': problem}), 400
    config = load_config()

    # Find the next available integer for group_id
    existing_group_ids = [int(group['group_id']) for group in config['groups']]
    next_group_id = max(existing_group_ids) + 1 if existing_group_ids else 1

    new_group = {
        "group_id": str(next_group_id),  # Use the next available integer
        **values
    }
    config['groups'].append(new_group)
    save_config(config)
    log_change(f"Group {new_group['group_id']} added: name={new_group['name']}, max_occupancy={new_group['max_occupancy']}")
    return jsonify({'status': 'success', 'group': new_group}), 200

# /api/groups/<group_id>/edit
@api_bp.route('/groups/<group_id>/edit', methods=['POST'])
@api_login_required(role='Administrator')
@with_config_lock
def edit_group(group_id):
    """
    Edit group
    ---
    post:
      description: Edits a group's name, welcome text, maximum occupancy, and maintenance mode status
      parameters:
        - in: path
          name: group_id
          schema:
            type: integer
          required: true
          description: The ID of the group to edit
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              properties:
                name:
                  type: string
                  description: The new name of the group
                  example: Group 1
                welcome_text:
                  type: string
                  description: The new welcome text of the group
                  example: Welcome to Group 1
                max_occupancy:
                  type: integer
                  description: The new maximum occupancy of the group
                  example: 10
                maintenance_mode:
                  type: boolean
                  description: The new maintenance mode status of the group
                  example: false
      responses:
        200:
          description: Group edited
          content:
            application/json:
              schema:
                type: object
                properties:
                  status:
                    type: string
                    description: The status of the edit operation
                    example: success
        404:
          description: Group not found
          content:
            application/json:
              schema:
                type: object
                properties:
                  status:
                    type: string
                    example: error
                  message:
                    type: string
                    example: Group not found
    """
    config = load_config()
    group = next((g for g in config['groups'] if str(g['group_id']) == group_id), None)
    if not group:
        return jsonify({'status': 'error', 'message': 'Group not found'}), 404
    values, problem = _group_values(request.get_json(silent=True) or {}, group)
    if problem:
        return jsonify({'status': 'error', 'message': problem}), 400

    group.update(values)
    save_config(config)
    log_change(f"Group {group_id} edited: name={group['name']}, welcome_text={group['welcome_text']}, max_occupancy={group['max_occupancy']}, maintenance_mode={group['maintenance_mode']}")
    return jsonify({'status': 'success'}), 200

# /api/groups/<group_id>/delete
@api_bp.route('/groups/<group_id>/delete', methods=['DELETE'])
@api_login_required(role='Administrator')
@with_config_lock
def delete_group(group_id):
    """
    Delete group
    ---
    delete:
      description: Deletes a group
      parameters:
        - in: path
          name: group_id
          schema:
            type: integer
          required: true
          description: The ID of the group to delete
      responses:
        200:
          description: Group deleted
          content:
            application/json:
              schema:
                type: object
                properties:
                  status:
                    type: string
                    description: The status of the delete operation
                    example: success
        404:
          description: Group not found
          content:
            application/json:
              schema:
                type: object
                properties:
                  status:
                    type: string
                    example: error
                  message:
                    type: string
                    example: Group not found
    """
    DEFAULT_GROUP_ID = '0'
    config = load_config()
    group = next((g for g in config['groups'] if str(g['group_id']) == group_id), None)
    if not group:
        return jsonify({'status': 'error', 'message': 'Group not found'}), 404

    assigned = [s for s in config['sensors'] if str(s['group_id']) == group_id]
    if assigned and group_id == DEFAULT_GROUP_ID:
        return jsonify({'status': 'error', 'message': 'Die Standardgruppe kann nicht gelöscht werden, solange ihr Sensoren zugeordnet sind'}), 400

    if assigned:
        # Sensors of the deleted group move to the default group, which is created once if missing
        if not any(str(g['group_id']) == DEFAULT_GROUP_ID for g in config['groups']):
            config['groups'].append({
                "group_id": DEFAULT_GROUP_ID,
                "name": "Standardgruppe",
                "max_occupancy": 100,
                "welcome_text": "keine Gruppe zugeordnet",
                "maintenance_mode": False
            })
        for sensor_config in assigned:
            sensor_config['group_id'] = DEFAULT_GROUP_ID
        # Keep the polled sensor objects in sync, they write group_id to the database
        for sensor in sensors:
            if str(sensor.group_id) == group_id:
                sensor.group_id = DEFAULT_GROUP_ID

    config['groups'] = [g for g in config['groups'] if str(g['group_id']) != group_id]
    save_config(config)
    _remove_display_images(group)
    log_change(f"Group {group_id} deleted: {len(assigned)} sensor(s) moved to group {DEFAULT_GROUP_ID}")
    return jsonify({'status': 'success'}), 200

# /api/groups/<group_id>/toggle_maintenance_mode
@api_bp.route('/groups/<group_id>/toggle_maintenance_mode', methods=['POST'])
@api_login_required(role='Administrator')
@with_config_lock
def toggle_maintenance_mode(group_id):
    """
    Toggle maintenance mode
    ---
    post:
      description: Toggles the maintenance mode of a group
      parameters:
        - in: path
          name: group_id
          schema:
            type: integer
          required: true
          description: The ID of the group to toggle maintenance mode
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              properties:
                maintenance_mode:
                  type: boolean
                  description: The new maintenance mode status of the group
                  example: true
      responses:
        200:
          description: Maintenance mode toggled
          content:
            application/json:
              schema:
                type: object
                properties:
                  status:
                    type: string
                    description: The status of the toggle operation
                    example: success
        404:
          description: Group not found
          content:
            application/json:
              schema:
                type: object
                properties:
                  status:
                    type: string
                    example: error
                  message:
                    type: string
                    example: Group not found
    """
    data = request.get_json(silent=True) or {}
    if not isinstance(data.get('maintenance_mode'), bool):
        return jsonify({'status': 'error', 'message': 'Der Wartungsmodus muss true oder false sein'}), 400
    config = load_config()
    group = next((g for g in config['groups'] if str(g['group_id']) == group_id), None)
    if group:
        group['maintenance_mode'] = data['maintenance_mode']
        save_config(config)
        log_change(f"Group {group_id} maintenance mode set to {data['maintenance_mode']}")
        return jsonify({'status': 'success'}), 200
    return jsonify({'status': 'error', 'message': 'Group not found'}), 404

# /api/groups/<group_id>/update-settings
@api_bp.route('/groups/<group_id>/update-settings', methods=['POST'])
@api_login_required(role='Administrator')
@with_config_lock
def update_group_settings(group_id):
    """
    Update group settings
    ---
    post:
      description: Updates a group's name, maximum occupancy, welcome text, and maintenance mode status
      parameters:
        - in: path
          name: group_id
          schema:
            type: integer
          required: true
          description: The ID of the group to update settings
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              properties:
                name:
                  type: string
                  description: The new name of the group
                  example: Group 1
                max_occupancy:
                  type: integer
                  description: The new maximum occupancy of the group
                  example: 10
                welcome_text:
                  type: string
                  description: The new welcome text of the group
                  example: Welcome to Group 1
                maintenance_mode:
                  type: boolean
                  description: The new maintenance mode status of the group
                  example: false
      responses:
        200:
          description: Group settings updated
          content:
            application/json:
              schema:
                type: object
                properties:
                  status:
                    type: string
                    description: The status of the update operation
                    example: success
        404:
          description: Group not found
          content:
            application/json:
              schema:
                type: object
                properties:
                  status:
                    type: string
                    example: error
                  message:
                    type: string
                    example: Group not found
    """
    config = load_config()
    group = next((g for g in config['groups'] if str(g['group_id']) == group_id), None)
    if not group:
        return jsonify({'status': 'error', 'message': 'Group not found'}), 404
    values, problem = _group_values(request.get_json(silent=True) or {}, group)
    if problem:
        return jsonify({'status': 'error', 'message': problem}), 400

    group.update(values)
    save_config(config)
    log_change(f"Group {group_id} settings updated: name={group['name']}, max_occupancy={group['max_occupancy']}, welcome_text={group['welcome_text']}, maintenance_mode={group['maintenance_mode']}")
    return jsonify({'status': 'success'}), 200

# /api/schedules
@api_bp.route('/schedules')
@api_login_required(role='Administrator')
def get_schedulers():
    """
    Get schedulers
    ---
    get:
      description: Returns a JSON object with schedulers
      responses:
        200:
          description: Schedulers
          content:
            application/json:
              schema:
                type: object
                properties:
                  schedulers:
                    type: array
                    description: An array of schedulers
                    items:
                      type: object
                      properties:
                        id:
                          type: integer
                          example: 1
                        action:
                          type: string
                          example: reboot
                        interval:
                          type: integer
                          example: 60
                        day:
                          type: string
                          example: Monday
                        time:
                          type: string
                          example: 08:00
                        sensors:
                          type: array
                          items:
                            type: integer
                            example: 1
        500:
          description: Internal server error
          content:
            application/json:
              schema:
                type: object
                properties:
                  error:
                    type: string
                    example: Error message
    """
    config = load_config()
    return jsonify({'schedules': config.get('schedules', [])}), 200

# /api/schedules/add
@api_bp.route('/schedules/add', methods=['PUT'])
@api_login_required(role='Administrator')
@with_config_lock
def add_schedule_route():
    """
    Add schedule
    ---
    put:"
    "description: Adds a schedule"
    "requestBody:"
    "required: true"
    "content:"
    "application/json:"
    "schema:"
    "type: object"
    "properties:"
    "action:"
    "type: string"
    "description: The action to perform"
    "example: reboot"
    "interval:"
    "type: integer"
    "description: The interval in seconds"
    "example: 60"
    "day:"
    "type: string"
    "description: The day of the week"
    "example: Monday"
    "time:"
    "type: string"
    "description: The time of day"
    "example: 08:00"
    "sensors:"
    "type: array"
    "description: An array of sensor IDs"
    "items:"
    "type: integer"
    "example: 1
    "responses:"
    "200:"
    "description: Schedule added"
    "content:"
    "application/json:"
    "schema:"
    "type: object"
    "properties:"
    "status:"
    "type: string"
    "description: The status of the add operation"
    "example: success
    "schedule:"
    "type: object"
    "description: The added schedule"
    "properties:"
    "id:"
    "type: integer"
    "example: 1
    "action:"
    "type: string"
    "example: reboot
    "interval:"
    "type: integer"
    "example: 60
    "day:"
    "type: string"
    "example: Monday
    "time:"
    "type: string"
    "example: 08:00
    "sensors:"
    "type: array"
    "items:"
    "type: integer"
    "example: 1
    "500:"
    "description: Internal server error"
    "content:"
    "application/json:"
    "schema:"
    "type: object"
    "properties:"
    "error:"
    "type: string"
    "example: Error message
    """
    data = request.get_json(silent=True) or {}
    new_schedule = {
        "action": data.get('action'),
        "interval": data.get('interval'),
        "day": data.get('day', ''),
        "time": data.get('time', ''),
        "sensors": data.get('sensors')
    }
    problem = validate_schedule(new_schedule)
    if problem:
        return jsonify({'status': 'error', 'message': problem}), 400

    config = load_config()

    # Find the next available integer for schedule_id
    existing_schedule_ids = [schedule['id'] for schedule in config.get('schedules', [])]
    new_schedule = {"id": max(existing_schedule_ids) + 1 if existing_schedule_ids else 1, **new_schedule}

    if 'schedules' not in config:
        config['schedules'] = []
    config['schedules'].append(new_schedule)
    save_config(config)

    # Add the new schedule to the scheduler
    scheduler_add_schedule(new_schedule)
    log_change(f"Schedule {new_schedule['id']} added: action={new_schedule['action']}, interval={new_schedule['interval']}, day={new_schedule['day']}, time={new_schedule['time']}, sensors={new_schedule['sensors']}")

    return jsonify({'status': 'success', 'schedule': new_schedule}), 200

# /api/schedules/<schedule_id>/edit
@api_bp.route('/schedules/<schedule_id>/edit', methods=['POST'])
@api_login_required(role='Administrator')
@with_config_lock
def edit_schedule_route(schedule_id):
    """
    Edit schedule
    ---
    post:
      description: Edits a schedule's action, interval, day, time, and sensor IDs
      parameters:
        - in: path
          name: schedule_id
          schema:
            type: integer
          required: true
          description: The ID of the schedule to edit
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              properties:
                action:
                  type: string
                  description: The new action to perform
                  example: reboot
                interval:
                  type: integer
                  description: The new interval in seconds
                  example: 60
                day:
                  type: string
                  description: The new day of the week
                  example: Monday
                time:
                  type: string
                  description: The new time of day
                  example: 08:00
                sensors:
                  type: array
                  description: An array of sensor IDs
                  items:
                    type: integer
                    example: 1
      responses:
        200:
          description: Schedule edited
          content:
            application/json:
              schema:
                type: object
                properties:
                  status:
                    type: string
                    description: The status of the edit operation
                    example: success
        404:
          description: Schedule not found
          content:
            application/json:
              schema:
                type: object
                properties:
                  status:
                    type: string
                    example: error
                  message:
                    type: string
                    example: Schedule not found
    """
    data = request.get_json(silent=True) or {}
    config = load_config()

    # Compare as strings: the id is an integer in config.json and a string in the URL
    schedule = next((s for s in config.get('schedules', []) if str(s.get('id')) == str(schedule_id)), None)
    if not schedule:
        return jsonify({'status': 'error', 'message': 'Schedule not found'}), 404

    updated = dict(schedule)
    for key in ('action', 'interval', 'day', 'time', 'sensors'):
        if key in data:
            updated[key] = data[key]
    problem = validate_schedule(updated)
    if problem:
        return jsonify({'status': 'error', 'message': problem}), 400

    schedule.update(updated)
    save_config(config)

    # Replace the job in the scheduler
    scheduler_edit_schedule(schedule['id'], schedule)
    log_change(f"Schedule {schedule['id']} edited: action={schedule['action']}, interval={schedule['interval']}, day={schedule['day']}, time={schedule['time']}, sensors={schedule['sensors']}")

    return jsonify({'status': 'success', 'schedule': schedule}), 200

# /api/schedules/<schedule_id>/delete
@api_bp.route('/schedules/<schedule_id>/delete', methods=['DELETE'])
@api_login_required(role='Administrator')
@with_config_lock
def delete_schedule_route(schedule_id):
    """
    Delete schedule
    ---
    delete:
      description: Deletes a schedule
      parameters:
        - in: path
          name: schedule_id
          schema:
            type: integer
          required: true
          description: The ID of the schedule to delete
      responses:
        200:
          description: Schedule deleted
          content:
            application/json:
              schema:
                type: object
                properties:
                  status:
                    type: string
                    description: The status of the delete operation
                    example: success
        404:
          description: Schedule not found
          content:
            application/json:
              schema:
                type: object
                properties:
                  status:
                    type: string
                    example: error
                  message:
                    type: string
                    example: Schedule not found
    """
    config = load_config()
    all_schedules = config.get('schedules', [])
    # Compare as strings: the id is an integer in config.json and a string in the URL
    removed = [s for s in all_schedules if str(s.get('id')) == str(schedule_id)]
    schedules = [s for s in all_schedules if str(s.get('id')) != str(schedule_id)]
    if not removed:
        return jsonify({'status': 'error', 'message': 'Schedule not found'}), 404

    config['schedules'] = schedules
    save_config(config)

    # Remove the job from the scheduler, so it stops running immediately
    for schedule in removed:
        scheduler_delete_schedule(schedule['id'])
        log_change(f"Schedule {schedule['id']} deleted")

    return jsonify({'status': 'success', 'schedules': schedules})



ALLOWED_IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
MAX_DISPLAY_IMAGES = 3


def _allowed_image(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_IMAGE_EXTENSIONS

def _upload_folder():
    return os.path.join(current_app.root_path, 'static', 'uploads')


# /api/groups/<group_id>/display_images  (POST = upload, GET = list)
@api_bp.route('/groups/<group_id>/display_images', methods=['GET', 'POST'])
@api_login_required(role='Administrator')
@with_config_lock
def group_display_images(group_id):
    config = load_config()
    group = next((g for g in config['groups'] if str(g['group_id']) == str(group_id)), None)
    if not group:
        return jsonify({'status': 'error', 'message': 'Group not found'}), 404

    if request.method == 'GET':
        images = group.get('display_images', [None, None, None])
        return jsonify({'status': 'success', 'display_images': images}), 200

    # POST: upload image to a slot
    slot = request.form.get('slot')
    if slot is None or not slot.isdigit() or not (0 <= int(slot) < MAX_DISPLAY_IMAGES):
        return jsonify({'status': 'error', 'message': 'Invalid slot (0-2)'}), 400
    slot = int(slot)

    file = request.files.get('file')
    if not file or file.filename == '':
        return jsonify({'status': 'error', 'message': 'No file provided'}), 400
    if not _allowed_image(file.filename):
        return jsonify({'status': 'error', 'message': 'File type not allowed'}), 400

    upload_folder = _upload_folder()
    ext = file.filename.rsplit('.', 1)[1].lower()
    filename = f"group_{group_id}_img_{slot}.{ext}"
    os.makedirs(upload_folder, exist_ok=True)

    # Remove old image file for this slot if different extension
    images = group.get('display_images', [None, None, None])
    while len(images) < MAX_DISPLAY_IMAGES:
        images.append(None)
    old = images[slot]
    if old and old != filename:
        old_path = os.path.join(upload_folder, old)
        if os.path.exists(old_path):
            os.remove(old_path)

    file.save(os.path.join(upload_folder, filename))
    images[slot] = filename
    group['display_images'] = images
    save_config(config)
    log_change(f"Group {group_id} display image slot {slot} updated: {filename}")
    return jsonify({'status': 'success', 'display_images': images}), 200


# /api/groups/<group_id>/display_images/<int:slot>  (DELETE)
@api_bp.route('/groups/<group_id>/display_images/<int:slot>', methods=['DELETE'])
@api_login_required(role='Administrator')
@with_config_lock
def delete_group_display_image(group_id, slot):
    if not (0 <= slot < MAX_DISPLAY_IMAGES):
        return jsonify({'status': 'error', 'message': 'Invalid slot (0-2)'}), 400
    config = load_config()
    group = next((g for g in config['groups'] if str(g['group_id']) == str(group_id)), None)
    if not group:
        return jsonify({'status': 'error', 'message': 'Group not found'}), 404

    images = group.get('display_images', [None, None, None])
    while len(images) < MAX_DISPLAY_IMAGES:
        images.append(None)

    old = images[slot]
    if old:
        old_path = os.path.join(_upload_folder(), old)
        if os.path.exists(old_path):
            os.remove(old_path)
    images[slot] = None
    group['display_images'] = images
    save_config(config)
    log_change(f"Group {group_id} display image slot {slot} deleted")
    return jsonify({'status': 'success', 'display_images': images}), 200
