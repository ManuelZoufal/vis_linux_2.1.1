"""
Credentials of the sensors

The values are looked up in this order, separately for user name and password:

1. SENSOR_<ID>_USERNAME / SENSOR_<ID>_PASSWORD   - one sensor
2. SENSOR_IEE_PASSWORD,
   SENSOR_HANWHA_USERNAME / SENSOR_HANWHA_PASSWORD - all sensors of a type
3. "username" / "password" in config.json          - old location, still supported

Keeping them in .env separates the secrets from config.json.
"""
import os
import re
from collections import Counter

# sensor type in config.json -> part of the environment variable name
TYPE_KEYS = {'IEE': 'IEE', 'AI_HANWHA': 'HANWHA'}
# which fields a sensor type needs
FIELDS_BY_TYPE = {'IEE': ('password',), 'AI_HANWHA': ('username', 'password')}

SOURCE_SENSOR = 'sensor'    # SENSOR_<ID>_...
SOURCE_TYPE = 'type'        # SENSOR_<TYPE>_...
SOURCE_CONFIG = 'config'    # config.json
SOURCE_MISSING = 'missing'


def sensor_env_key(sensor_id, field):
    """Name of the environment variable for one sensor"""
    return f"SENSOR_{re.sub(r'[^A-Za-z0-9]', '_', str(sensor_id)).upper()}_{field.upper()}"


def type_env_key(sensor_type, field):
    """Name of the environment variable for all sensors of a type"""
    return f"SENSOR_{TYPE_KEYS[sensor_type]}_{field.upper()}"


def resolve_field(sensor_config, field, env=None):
    """
    Look up one credential field of a sensor

    Returns:
    tuple: (value, source) - value is '' if nothing is configured
    """
    env = os.environ if env is None else env
    value = env.get(sensor_env_key(sensor_config['sensor_id'], field))
    if value:
        return value, SOURCE_SENSOR
    value = env.get(type_env_key(sensor_config['type'], field))
    if value:
        return value, SOURCE_TYPE
    value = sensor_config.get(field)
    if value:
        return value, SOURCE_CONFIG
    return '', SOURCE_MISSING


def resolve(sensor_config, env=None):
    """
    Look up all credential fields a sensor needs

    Returns:
    dict: field -> (value, source); empty for sensor types without credentials
    """
    fields = FIELDS_BY_TYPE.get(sensor_config.get('type'), ())
    return {field: resolve_field(sensor_config, field, env) for field in fields}


def apply_to_sensors(sensors, config, env=None):
    """
    Give the running sensor objects the currently configured credentials,
    so a change applies without a restart

    Args:
    sensors (list): Sensor objects
    config (dict): Content of config.json
    """
    by_id = {s['sensor_id']: s for s in config['sensors']}
    for sensor in sensors:
        sensor_config = by_id.get(sensor.sensor_id)
        if not sensor_config:
            continue
        for field, (value, _source) in resolve(sensor_config, env).items():
            setattr(sensor, field, value)


def plan_migration(config, env=None):
    """
    Work out which environment variables are needed so that no sensor depends
    on the credentials in config.json any more

    For every sensor type the most frequent value becomes the type default
    (unless one is already set); sensors with a different value get their own
    variable.

    Returns:
    dict: environment variable name -> value (empty if nothing is left in config.json)
    """
    env = dict(os.environ if env is None else env)
    new_values = {}
    for sensor_type, fields in FIELDS_BY_TYPE.items():
        type_sensors = [s for s in config['sensors'] if s.get('type') == sensor_type]
        for field in fields:
            legacy = {s['sensor_id']: s[field] for s in type_sensors
                      if resolve_field(s, field, env)[1] == SOURCE_CONFIG}
            if not legacy:
                continue
            type_key = type_env_key(sensor_type, field)
            type_default = env.get(type_key)
            if not type_default:
                type_default = Counter(legacy.values()).most_common(1)[0][0]
                new_values[type_key] = type_default
                env[type_key] = type_default
            for sensor_id, value in legacy.items():
                if value != type_default:
                    new_values[sensor_env_key(sensor_id, field)] = value
    return new_values


def strip_from_config(config):
    """
    Remove user names and passwords of the sensors from the configuration

    Returns:
    int: Number of sensors that had credentials removed
    """
    changed = 0
    for sensor_config in config['sensors']:
        removed = [sensor_config.pop(field) for field in ('username', 'password') if field in sensor_config]
        if removed:
            changed += 1
    return changed
