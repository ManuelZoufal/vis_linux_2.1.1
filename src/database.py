import sqlite3
import os
import json
import time

from werkzeug.security import generate_password_hash

def create_sensor_table(conn):
    """
    Create sensor_data table

    param conn: sqlite3 connection object
    """
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sensor_data (
            sensor_id TEXT PRIMARY KEY,
            sensor_name TEXT,
            ip_address TEXT UNIQUE,
            group_id TEXT,
            forward_value INTEGER,
            backward_value INTEGER,
            occupancy INTEGER,
            datapoint_id TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    

def create_users_table(conn):
    """
    Create users table

    param conn: sqlite3 connection object
    """
    cursor = conn.cursor()
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        role TEXT NOT NULL
    )
    ''')
    conn.commit()
    

def create_roles_table(conn):
    """
    Create roles table

    param conn: sqlite3 connection object
    """
    cursor = conn.cursor()
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS roles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL
    )
    ''')
    conn.commit()
    

def create_schedules_table(conn):
    """
    Create schedules table

    param conn: sqlite3 connection object
    """
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS schedules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action TEXT NOT NULL,
            interval TEXT NOT NULL,
            day TEXT,
            time TEXT NOT NULL,
            sensors TEXT NOT NULL
        )
    ''')
    conn.commit()
    

def add_role(conn, role):
    """
    Insert role into roles table

    param conn: sqlite3 connection object
    param role: role name
    """
    cursor = conn.cursor()
    cursor.execute('INSERT OR IGNORE INTO roles (name) VALUES (?)', (role,))
    conn.commit()


def init_db():
    """
    Initialize database
    
    Creates sensor_data, users, roles and schedules tables
    Inserts default roles into roles table
    Inserts initial admin user into
    users table

    """
    # Create sensor_data database, delete if already exists
    if os.path.exists('sensor_data.db'):
        os.remove('sensor_data.db')
    conn = sqlite3.connect('sensor_data.db')

    create_sensor_table(conn)
    create_users_table(conn)
    create_roles_table(conn)
    create_schedules_table(conn)

    add_role(conn, 'Administrator')
    add_role(conn, 'Benutzer')
    add_role(conn, 'Betrachter')

    # Insert initial admin user
    hashed_password = generate_password_hash(os.environ.get("DEFAULT_ADMIN_PASSWORD", "admin123"), method='pbkdf2:sha256')
    cursor = conn.cursor()
    cursor.execute('INSERT OR IGNORE INTO users (username, password, role) VALUES (?, ?, ?)', (os.environ.get("DEFAULT_ADMIN_USER", "admin"), hashed_password, 'Administrator'))
    conn.commit()

    conn.close()

def get_connection():
    """
    Get connection to sensor_data database"

    return: sqlite3 connection object
    """
    conn = sqlite3.connect('sensor_data.db')
    conn.row_factory = sqlite3.Row
    return conn

def save_sensor_values(sensor):
    """
    Save sensor values to sensor_data table

    param sensor: Sensor object
    """
    conn = get_connection()
    cursor = conn.cursor()
    if sensor.datapoint_id is None:
        sensor.datapoint_id = ''
    cursor.execute('''
        INSERT or REPLACE INTO sensor_data (sensor_id, sensor_name, ip_address, group_id, forward_value, backward_value, occupancy, datapoint_id, timestamp)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
    ''', (sensor.sensor_id, sensor.name, sensor.ip_address, sensor.group_id, sensor.forward_value, sensor.backward_value, sensor.occupancy, sensor.datapoint_id))
    conn.commit()
    conn.close()

def get_occpancy_by_group():
    """
    Get occupancy values by group_id

    param group_id: group_id

    return: list of occupancy values
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT group_id, SUM(occupancy) as total_occupancy
        FROM sensor_data
        GROUP BY group_id
    ''')
    rows = cursor.fetchall()
    conn.close()
    return rows

def save_schedule(action, interval, day, time, sensors):
    """
    Save schedule to schedules table

    param action: action to be performed
    param interval: interval of action
    param day: day of action
    param time: time of action
    param sensors: sensors on which action is to be performed
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO schedules (action, interval, day, time, sensors)
        VALUES (?, ?, ?, ?, ?)
    ''', (action, interval, day, time, json.dumps(sensors)))
    conn.commit()
    conn.close()

def get_schedules():
    """
    Get all schedules from schedules table

    return: list of schedules
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM schedules')
    rows = cursor.fetchall()
    schedules = []
    for row in rows:
        schedules.append({
            'id': row[0],
            'action': row[1],
            'interval': row[2],
            'day': row[3],
            'time': row[4],
            'sensors': json.loads(row[5])
        })
    conn.close()
    return schedules

def db_output_thread(interval):
    """
    Print sensor_data table rows at regular intervals

    param interval: interval in seconds
    """
    while True:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM sensor_data')
        rows = cursor.fetchall()
        #for row in rows:
            #print(f"ID: {row['sensor_id']} | Name: {row['sensor_name']} | IP: {row['ip_address']} | Group: {row['group_id']} | Forward: {row['forward_value']} | Backward: {row['backward_value']} | Occupancy: {row['occupancy']} | Datapoint ID: {row['datapoint_id']} | Timestamp: {row['timestamp']}")
        conn.close()
        time.sleep(interval)








