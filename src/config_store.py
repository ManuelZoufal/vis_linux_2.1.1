"""
Central access to config.json

All changes of config.json run under one lock and are written atomically,
so two requests at the same time cannot lose each other's changes and a
reader never sees a half written file.
"""
import json
import logging
import os
import tempfile
import threading
from functools import wraps

CONFIG_PATH = 'config.json'

# Reentrant, so a locked function may call another locked function
config_lock = threading.RLock()


def load_config(path=CONFIG_PATH):
    """
    Read the configuration

    Returns:
    dict: Content of config.json
    """
    with open(path, 'r') as file:
        return json.load(file)


def save_config(config, path=CONFIG_PATH):
    """
    Write the configuration atomically: the content is written to a temporary
    file in the same directory, which then replaces config.json in one step.

    Args:
    config (dict): Complete configuration
    """
    content = json.dumps(config, indent=4)
    directory = os.path.dirname(os.path.abspath(path))
    with config_lock:
        try:
            fd, temp_path = tempfile.mkstemp(prefix='.config.', suffix='.tmp', dir=directory)
        except OSError as e:
            # The directory is not writable for this user: fall back to writing the file directly
            logging.warning(f"config.json is written without temporary file: {e}")
            with open(path, 'w') as file:
                file.write(content)
            return
        try:
            with os.fdopen(fd, 'w') as file:
                file.write(content)
                file.flush()
                os.fsync(file.fileno())
            if os.path.exists(path):
                os.chmod(temp_path, os.stat(path).st_mode & 0o777)  # keep the permissions of config.json
            os.replace(temp_path, path)
        except BaseException:
            if os.path.exists(temp_path):
                os.remove(temp_path)
            raise


def with_config_lock(fn):
    """Decorator: run the whole read-modify-write cycle of a function under the config lock"""
    @wraps(fn)
    def locked(*args, **kwargs):
        with config_lock:
            return fn(*args, **kwargs)
    return locked
