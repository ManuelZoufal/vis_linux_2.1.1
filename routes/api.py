from . import api_bp

from src.sensor import sensors
from src.helpers import get_local_ip, log_change, api_login_required
from src.scheduler import add_schedule as scheduler_add_schedule, edit_schedule as scheduler_edit_schedule, delete_schedule as scheduler_delete_schedule, validate_schedule
from src.database import get_connection, save_sensor_values
from src import thread_status

from flask import jsonify, session, request, send_file, current_app
from werkzeug.utils import secure_filename
from datetime import datetime, timezone, timedelta
from threading import enumerate as enumerate_threads
import json
import sqlite3
import socket
import io
import os



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
    with open('config.json', 'r') as file:
        config = json.load(file)
    
    # Combine sensor data from the config file and the database
    sensor_data = [{
        'sensor_id': sensor['sensor_id'],
        'name': sensor['name'],
        'ip_address': sensor.get('ip_address', 'N/A'),
        'group_id': sensor['group_id'],
        'occupancy': next((row[2] for row in db_data if row[0] == sensor['sensor_id']), sensor.get('occupancy', 0)),
        'forward_value': next((row[3] for row in db_data if row[0] == sensor['sensor_id']), 0),
        'backward_value': next((row[4] for row in db_data if row[0] == sensor['sensor_id']), 0),
        'datapoint_id': next((row[5] for row in db_data if row[0] == sensor['sensor_id']), "N/A"),
        'timestamp': next((row[6] for row in db_data if row[0] == sensor['sensor_id']), 'N/A'),
        'type': sensor['type']
    } for sensor in config['sensors']]

    # Convert timestamps to the desired timezone
    for sensor in sensor_data:
        if sensor['timestamp'] != 'N/A':
            dt = datetime.strptime(sensor['timestamp'], '%Y-%m-%d %H:%M:%S')
            dt = dt.replace(tzinfo=timezone.utc).astimezone(timezone(timedelta(hours=1)))  # Adjust to your desired timezone
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
    # Get the log messages from the session
    logs = []
    try:
        # Read log messages from the change_log.txt file
        with open('change_log.txt', 'r') as file:
            for line in file:
                timestamp, message = line.strip().split(' - ', 1)
                logs.append({'timestamp': timestamp, 'message': message})
        return jsonify({'logs': logs}), 200
    # Handle exceptions
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    
# /api/debug_info
@api_bp.route('/debug_info')
def get_debug_info():
    """
    Get debug information
    ---
    get:
      description: Returns a JSON object with debug information
      responses:
        200:
          description: Debug information
          content:
            application/json:
              schema:
                type: object
                properties:
                  debug_info:
                    type: array
                    description: An array of debug messages
                    items:
                      type: object
                      properties:
                        timestamp:
                          type: string
                          description: The timestamp of the debug message
                          example:
                        message:
                          type: string
                          description: The debug message
                          example:
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
        # Get debug information from the threads
        debug_info = []
        # Enumerate all threads and check if they are active
        for thread in enumerate_threads():
            debug_info.append({
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'message': f'Thread "{thread.name}" is {"active" if thread.is_alive() else "inactive"}'
            })
        return jsonify({'debug_info': debug_info}), 200
    return jsonify({'error': 'Unauthorized to view debug information'}), 403

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
            'threads': thread_status.snapshot()
        }), 200
    return jsonify({'error': 'Unauthorized to view thread status'}), 403

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

# /api/export_debug_info
@api_bp.route('/debug_info/export')
def export_debug_info():
    """
    Export debug information
    ---
    get:
      description: Returns a file download of the debug information
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
        lines = []
        for thread in enumerate_threads():
            lines.append(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - Thread \"{thread.name}\" is {'active' if thread.is_alive() else 'inactive'}\n")
        content = io.BytesIO(''.join(lines).encode('utf-8'))
        return send_file(content, as_attachment=True, download_name='debug_info.txt', mimetype='text/plain')        
    return jsonify({'error': 'Unauthorized to export debug information'}), 403

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
    if sensor:
        sensor.reset_sensor_values()
        log_change(f"Sensor {sensor_id} reset")
        return jsonify({'status': 'success'}), 200
    return jsonify({'status': 'error', 'message': 'Sensor not found'}), 404

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
    if sensor:
        sensor.reboot_sensor()
        log_change(f"Sensor {sensor_id} rebooted")
        return jsonify({'status': 'success'}), 200
    return jsonify({'status': 'error', 'message': 'Sensor not found'}), 404

# /api/sensors/<sensor_id>/edit
@api_bp.route('/sensors/<sensor_id>/edit', methods=['POST'])
@api_login_required(role='Administrator')
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
    if sensor:
        data = request.json
        sensor.name = data.get('name', sensor.name)
        sensor.group_id = data.get('group_id', sensor.group_id)
        sensor.datapoint_id = data.get('datapoint_id', sensor.datapoint_id)
        # Save changes to config file
        with open('config.json', 'r') as file:
            config = json.load(file)
        for sensor_config in config['sensors']:
            if sensor_config['sensor_id'] == sensor_id:
                sensor_config['name'] = sensor.name
                sensor_config['group_id'] = sensor.group_id
                sensor_config['datapoint_id'] = sensor.datapoint_id
                break
        with open('config.json', 'w') as file:
            json.dump(config, file, indent=4)
        log_change(f"Sensor {sensor_id} edited: name={sensor.name}, group_id={sensor.group_id}, datapoint_id={sensor.datapoint_id}")
        save_sensor_values(sensor)
        return jsonify({'status': 'success'}), 200
    return jsonify({'status': 'error', 'message': 'Sensor not found'}), 404

# /api/sensors/virtual/add
@api_bp.route('/sensors/virtual/add', methods=['PUT'])
@api_login_required(role='Administrator')
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
    with open('config.json', 'r') as file:
        config = json.load(file)
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
    with open('config.json', 'w') as file:
        json.dump(config, file, indent=4)
    log_change(f"Virtual sensor {new_sensor['sensor_id']} added: name={new_sensor['name']}, group_id={new_sensor['group_id']}, occupancy={new_sensor['occupancy']}")
    return jsonify({'status': 'success', 'sensor': new_sensor}), 200

# /api/sensors/virtual/<sensor_id>/edit
@api_bp.route('/sensors/virtual/<sensor_id>/edit', methods=['POST'])
@api_login_required(role='Administrator')
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
    with open('config.json', 'r') as file:
        config = json.load(file)
    sensor = next((s for s in config['sensors'] if s['sensor_id'] == sensor_id), None)
    if not sensor or sensor['type'] != 'VIRTUAL':
        return jsonify({'status': 'error', 'message': 'Sensor not found or not virtual'}), 404

    values, problem = _virtual_sensor_values(request.get_json(silent=True) or {}, sensor)
    if problem:
        return jsonify({'status': 'error', 'message': problem}), 400
    if not any(str(g['group_id']) == values['group_id'] for g in config['groups']):
        return jsonify({'status': 'error', 'message': 'Gruppe nicht gefunden'}), 400

    sensor.update(values)
    with open('config.json', 'w') as file:
        json.dump(config, file, indent=4)
    log_change(f"Virtual sensor {sensor_id} edited: name={sensor['name']}, group_id={sensor['group_id']}, occupancy={sensor['occupancy']}")
    return jsonify({'status': 'success', 'sensor': sensor}), 200

# /api/sensors/virtual/<sensor_id>/delete 
@api_bp.route('/sensors/virtual/<sensor_id>/delete', methods=['DELETE'])
@api_login_required(role='Administrator')
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
    with open('config.json', 'r') as file:
        config = json.load(file)
    sensor = next((s for s in config['sensors'] if s['sensor_id'] == sensor_id), None)
    if sensor and sensor['type'] == 'VIRTUAL':
        config['sensors'] = [s for s in config['sensors'] if s['sensor_id'] != sensor_id]
        with open('config.json', 'w') as file:
            json.dump(config, file, indent=4)
        log_change(f"Virtual sensor {sensor_id} deleted")
        return jsonify({'status': 'success'}), 200
    return jsonify({'status': 'error', 'message': 'Sensor not found or not virtual'}), 404

# /api/groups/add
@api_bp.route('/groups/add', methods=['PUT'])
@api_login_required(role='Administrator')
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
    data = request.json
    with open('config.json', 'r') as file:
        config = json.load(file)
    
    # Find the next available integer for group_id
    existing_group_ids = [int(group['group_id']) for group in config['groups']]
    next_group_id = max(existing_group_ids) + 1 if existing_group_ids else 1

    new_group = {
        "group_id": str(next_group_id),  # Use the next available integer
        "name": data['name'],
        "max_occupancy": data['max_occupancy'],
        "welcome_text": data['welcome_text'],
        "maintenance_mode": data.get('maintenance_mode', False)
    }
    config['groups'].append(new_group)
    with open('config.json', 'w') as file:
        json.dump(config, file, indent=4)
    return jsonify({'status': 'success', 'group': new_group}), 200

# /api/groups/<group_id>/edit
@api_bp.route('/groups/<group_id>/edit', methods=['POST'])
@api_login_required(role='Administrator')
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
    data = request.json
    with open('config.json', 'r') as file:
        config = json.load(file)
    
    group = next((g for g in config['groups'] if str(g['group_id']) == group_id), None)
    if group:
        group['name'] = data.get('name', group['name'])
        group['welcome_text'] = data.get('welcome_text', group['welcome_text'])
        group['max_occupancy'] = data.get('max_occupancy', group['max_occupancy'])
        group['maintenance_mode'] = data.get('maintenance_mode', group.get('maintenance_mode', False))
        
        with open('config.json', 'w') as file:
            json.dump(config, file, indent=4)
        
        log_change(f"Group {group_id} edited: name={group['name']}, welcome_text={group['welcome_text']}, max_occupancy={group['max_occupancy']}, maintenance_mode={group['maintenance_mode']}")
        return jsonify({'status': 'success'}), 200
    return jsonify({'status': 'error', 'message': 'Group not found'}), 404

# /api/groups/<group_id>/delete
@api_bp.route('/groups/<group_id>/delete', methods=['DELETE'])
@api_login_required(role='Administrator')
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
    with open('config.json', 'r') as file:
        config = json.load(file)
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
    with open('config.json', 'w') as file:
        json.dump(config, file, indent=4)
    log_change(f"Group {group_id} deleted: {len(assigned)} sensor(s) moved to group {DEFAULT_GROUP_ID}")
    return jsonify({'status': 'success'}), 200

# /api/groups/<group_id>/toggle_maintenance_mode
@api_bp.route('/groups/<group_id>/toggle_maintenance_mode', methods=['POST'])
@api_login_required(role='Administrator')
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
    data = request.json
    with open('config.json', 'r') as file:
        config = json.load(file)
    group = next((g for g in config['groups'] if str(g['group_id']) == group_id), None)
    if group:
        group['maintenance_mode'] = data['maintenance_mode']
        with open('config.json', 'w') as file:
            json.dump(config, file, indent=4)
        log_change(f"Group {group_id} maintenance mode set to {data['maintenance_mode']}")
        return jsonify({'status': 'success'}), 200
    return jsonify({'status': 'error', 'message': 'Group not found'}), 404

# /api/groups/<group_id>/update-settings
@api_bp.route('/groups/<group_id>/update-settings', methods=['POST'])
@api_login_required(role='Administrator')
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
    data = request.json
    with open('config.json', 'r') as file:
        config = json.load(file)
    group = next((g for g in config['groups'] if str(g['group_id']) == group_id), None)
    if not group:
        return jsonify({'status': 'error', 'message': 'Group not found'}), 404
    group['name'] = data.get('name', group['name'])
    group['max_occupancy'] = data.get('max_occupancy', group['max_occupancy'])
    group['welcome_text'] = data.get('welcome_text', group['welcome_text'])
    group['maintenance_mode'] = data.get('maintenance_mode', group.get('maintenance_mode', False))

    with open('config.json', 'w') as file:
        json.dump(config, file, indent=4)
    log_change(f"Group {group_id} settings updated: name={data.get('name')}, max_occupancy={data.get('max_occupancy')}, welcome_text={data.get('welcome_text')}, maintenance_mode={data.get('maintenance_mode')}")
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
    with open('config.json', 'r') as file:
        config = json.load(file)
    return jsonify({'schedules': config.get('schedules', [])}), 200

# /api/schedules/add
@api_bp.route('/schedules/add', methods=['PUT'])
@api_login_required(role='Administrator')
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

    with open('config.json', 'r') as file:
        config = json.load(file)

    # Find the next available integer for schedule_id
    existing_schedule_ids = [schedule['id'] for schedule in config.get('schedules', [])]
    new_schedule = {"id": max(existing_schedule_ids) + 1 if existing_schedule_ids else 1, **new_schedule}

    if 'schedules' not in config:
        config['schedules'] = []
    config['schedules'].append(new_schedule)
    with open('config.json', 'w') as file:
        json.dump(config, file, indent=4)

    # Add the new schedule to the scheduler
    scheduler_add_schedule(new_schedule)
    log_change(f"Schedule {new_schedule['id']} added: action={new_schedule['action']}, interval={new_schedule['interval']}, day={new_schedule['day']}, time={new_schedule['time']}, sensors={new_schedule['sensors']}")

    return jsonify({'status': 'success', 'schedule': new_schedule}), 200

# /api/schedules/<schedule_id>/edit
@api_bp.route('/schedules/<schedule_id>/edit', methods=['POST'])
@api_login_required(role='Administrator')
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
    with open('config.json', 'r') as file:
        config = json.load(file)

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
    with open('config.json', 'w') as file:
        json.dump(config, file, indent=4)

    # Replace the job in the scheduler
    scheduler_edit_schedule(schedule['id'], schedule)
    log_change(f"Schedule {schedule['id']} edited: action={schedule['action']}, interval={schedule['interval']}, day={schedule['day']}, time={schedule['time']}, sensors={schedule['sensors']}")

    return jsonify({'status': 'success', 'schedule': schedule}), 200

# /api/schedules/<schedule_id>/delete
@api_bp.route('/schedules/<schedule_id>/delete', methods=['DELETE'])
@api_login_required(role='Administrator')
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
    with open('config.json', 'r') as file:
        config = json.load(file)
    all_schedules = config.get('schedules', [])
    # Compare as strings: the id is an integer in config.json and a string in the URL
    removed = [s for s in all_schedules if str(s.get('id')) == str(schedule_id)]
    schedules = [s for s in all_schedules if str(s.get('id')) != str(schedule_id)]
    if not removed:
        return jsonify({'status': 'error', 'message': 'Schedule not found'}), 404

    config['schedules'] = schedules
    with open('config.json', 'w') as file:
        json.dump(config, file, indent=4)

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
def group_display_images(group_id):
    with open('config.json', 'r') as f:
        config = json.load(f)
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
    with open('config.json', 'w') as f:
        json.dump(config, f, indent=4)
    log_change(f"Group {group_id} display image slot {slot} updated: {filename}")
    return jsonify({'status': 'success', 'display_images': images}), 200


# /api/groups/<group_id>/display_images/<int:slot>  (DELETE)
@api_bp.route('/groups/<group_id>/display_images/<int:slot>', methods=['DELETE'])
@api_login_required(role='Administrator')
def delete_group_display_image(group_id, slot):
    if not (0 <= slot < MAX_DISPLAY_IMAGES):
        return jsonify({'status': 'error', 'message': 'Invalid slot (0-2)'}), 400
    with open('config.json', 'r') as f:
        config = json.load(f)
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
    with open('config.json', 'w') as f:
        json.dump(config, f, indent=4)
    log_change(f"Group {group_id} display image slot {slot} deleted")
    return jsonify({'status': 'success', 'display_images': images}), 200
