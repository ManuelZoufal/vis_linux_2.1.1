import sqlite3
import os

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
    

    

    


def init_db():
    """
    Initialize database

    Creates the sensor_data and users tables if they do not exist
    Inserts initial admin user into users table if it does not exist

    Users and their passwords are kept across restarts. Only the sensor
    values are cleared, because they are read again from the sensors.
    """
    conn = sqlite3.connect('sensor_data.db')

    create_sensor_table(conn)
    create_users_table(conn)

    # Remove sensor values of the previous run (e.g. of sensors no longer in config.json)
    conn.execute('DELETE FROM sensor_data')
    conn.commit()

    # Insert initial admin user; an existing user with this name keeps its password
    hashed_password = generate_password_hash(os.environ["DEFAULT_ADMIN_PASSWORD"], method='pbkdf2:sha256')
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
