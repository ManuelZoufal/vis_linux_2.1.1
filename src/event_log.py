"""
Event log and time-limited detail log

Event log (always on, logs/events.log)
    One JSON object per line: failures, recoveries, executed schedules and
    other noteworthy events. Successful sensor requests are not recorded.

Detail log (switched on by an administrator for a chosen time)
    One text line per request to a sensor or to Navigator, including the
    successful ones. It switches itself off when the time is over or the
    file reaches the size limit.

Every log file is limited to LOG_MAX_MB (default 200 MB). Passwords, tokens
and request bodies are never written.
"""
import json
import logging
import os
import re
import threading
import time
from datetime import datetime, timedelta

LOG_DIR = os.environ.get('LOG_DIR', 'logs')
MAX_BYTES = int(os.environ.get('LOG_MAX_MB', 200)) * 1024 * 1024
DETAIL_KEEP_FILES = int(os.environ.get('LOG_DETAIL_KEEP', 5))

EVENT_FILE = 'events.log'
TIME_FORMAT = '%Y-%m-%d %H:%M:%S'
DETAIL_NAME = re.compile(r'^detail_\d{8}_\d{6}\.log$')

MAX_EVENT_MESSAGE = 2000
MAX_DETAIL_BODY = 200

_lock = threading.Lock()
_enabled = False
_detail = {'path': None, 'until': 0.0, 'scope': 'all', 'started': None, 'bytes': 0, 'stop_reason': None}


def shorten(text, limit=300):
    """Turn a text into a single line of at most `limit` characters"""
    text = ' '.join(str(text).split())
    return text if len(text) <= limit else text[:limit - 1] + '…'


def init():
    """
    Create the log directory; called once at startup

    Returns:
    bool: True if the logs can be written
    """
    global _enabled
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        with open(os.path.join(LOG_DIR, EVENT_FILE), 'a'):
            pass
        _enabled = True
    except OSError as e:
        _enabled = False
        logging.warning(f"Log directory {LOG_DIR} is not writable, event and detail log are disabled: {e}")
    return _enabled


# ---- Event log ---------------------------------------------------------------

def event(kind, source, message, label=None):
    """
    Write one entry to the event log

    Args:
    kind (str): error, ongoing, recovered, ended, schedule, navigator, detail, start
    source (str): Thread or component the event belongs to
    message (str): Description
    label (str, optional): Name shown in the user interface
    """
    if not _enabled:
        return
    entry = {
        'ts': datetime.now().strftime(TIME_FORMAT),
        'kind': kind,
        'source': source,
        'label': label or source,
        'message': shorten(message, MAX_EVENT_MESSAGE),
    }
    line = json.dumps(entry, ensure_ascii=False) + '\n'
    path = os.path.join(LOG_DIR, EVENT_FILE)
    try:
        with _lock:
            if os.path.exists(path) and os.path.getsize(path) + len(line.encode('utf-8')) > MAX_BYTES:
                os.replace(path, path + '.1')  # keep one previous file, drop the one before
            with open(path, 'a', encoding='utf-8') as file:
                file.write(line)
    except OSError as e:
        logging.warning(f"Event log could not be written: {e}")


def _lines_backwards(path, block_size=65536):
    """Yield the lines of a text file from the last to the first without reading it completely"""
    with open(path, 'rb') as file:
        file.seek(0, os.SEEK_END)
        position = file.tell()
        rest = b''
        while position > 0:
            read = min(block_size, position)
            position -= read
            file.seek(position)
            block = file.read(read) + rest
            lines = block.split(b'\n')
            rest = lines[0]
            for line in reversed(lines[1:]):
                if line:
                    yield line.decode('utf-8', errors='replace')
        if rest:
            yield rest.decode('utf-8', errors='replace')


def read_events(hours=24, source=None, limit=2000):
    """
    Read the newest events

    Args:
    hours (float | None): Only events of the last hours, None for all
    source (str | None): Only events of this source
    limit (int): Maximum number of events

    Returns:
    tuple: (list of events, newest first; True if more events matched than `limit`)
    """
    since = (datetime.now() - timedelta(hours=hours)).strftime(TIME_FORMAT) if hours else None
    events = []
    base = os.path.join(LOG_DIR, EVENT_FILE)
    for path in (base, base + '.1'):
        if not os.path.exists(path):
            continue
        for line in _lines_backwards(path):
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if since and entry.get('ts', '') < since:
                return events, False  # entries are written in time order
            if source and entry.get('source') != source:
                continue
            if len(events) >= limit:
                return events, True
            events.append(entry)
    return events, False


# ---- Detail log --------------------------------------------------------------

def _in_scope(source):
    scope = _detail['scope']
    if scope == 'all':
        return True
    if scope == 'sensors':
        return source.startswith('SensorThread-')
    if scope == 'navigator':
        return source == 'NavigatorUploadThread'
    if scope == 'scheduler':
        return source == 'SchedulerThread'
    if scope.startswith('sensor:'):
        return source == f"SensorThread-{scope.split(':', 1)[1]}"
    return False


def _stop_locked(reason):
    if _detail['path']:
        _detail.update(until=0.0, stop_reason=reason)
        path, _detail['path'] = _detail['path'], None
        return os.path.basename(path)
    return None


def detail_active(source=None):
    """True if the detail log is running (and records this source)"""
    if not _detail['path']:
        return False
    if time.time() >= _detail['until']:
        with _lock:
            stopped = _stop_locked('Zeit abgelaufen')
        if stopped:
            event('detail', 'DetailLog', f"Detail-Protokoll beendet (Zeit abgelaufen): {stopped}", 'Detail-Protokoll')
        return False
    return source is None or _in_scope(source)


def detail(source, message):
    """Write one line to the detail log if it is running and records this source"""
    if not detail_active(source):
        return
    now = datetime.now()
    line = f"{now.strftime(TIME_FORMAT)}.{now.microsecond // 1000:03d} | {source} | {shorten(message, 1000)}\n"
    data = line.encode('utf-8')
    stopped = None
    try:
        with _lock:
            if not _detail['path']:
                return
            if _detail['bytes'] + len(data) > MAX_BYTES:
                stopped = _stop_locked('Größenlimit erreicht')
            else:
                with open(_detail['path'], 'ab') as file:
                    file.write(data)
                _detail['bytes'] += len(data)
    except OSError as e:
        logging.warning(f"Detail log could not be written: {e}")
    if stopped:
        event('detail', 'DetailLog', f"Detail-Protokoll beendet (Größenlimit erreicht): {stopped}", 'Detail-Protokoll')


def start_detail(minutes, scope):
    """
    Switch the detail log on for a limited time; a running one is replaced

    Args:
    minutes (int): Duration
    scope (str): all, sensors, navigator, scheduler or sensor:<id>

    Returns:
    str: Name of the new file

    Raises:
    OSError: If the file cannot be created
    """
    if not _enabled:
        raise OSError(f"Das Verzeichnis {LOG_DIR} ist nicht beschreibbar")
    stop_detail('durch neues Detail-Protokoll ersetzt')
    now = datetime.now()
    name = f"detail_{now.strftime('%Y%m%d_%H%M%S')}.log"
    path = os.path.join(LOG_DIR, name)
    until = now + timedelta(minutes=minutes)
    header = (f"# VIS Detail-Protokoll | Start {now.strftime(TIME_FORMAT)} | geplantes Ende {until.strftime(TIME_FORMAT)} "
              f"| Umfang {scope}\n# Zeit | Quelle | Anfrage | Ergebnis | Dauer | Antwort (gekürzt)\n").encode('utf-8')
    with _lock:
        with open(path, 'wb') as file:
            file.write(header)
        _detail.update(path=path, until=until.timestamp(), scope=scope, started=now.strftime(TIME_FORMAT),
                       bytes=len(header), stop_reason=None)
    _remove_old_detail_files()
    event('detail', 'DetailLog', f"Detail-Protokoll gestartet für {minutes} Minuten, Umfang {scope}: {name}", 'Detail-Protokoll')
    return name


def stop_detail(reason='manuell beendet'):
    """Switch the detail log off; returns the file name or None if it was not running"""
    with _lock:
        stopped = _stop_locked(reason)
    if stopped:
        event('detail', 'DetailLog', f"Detail-Protokoll beendet ({reason}): {stopped}", 'Detail-Protokoll')
    return stopped


def detail_files():
    """List the detail log files, newest first"""
    if not os.path.isdir(LOG_DIR):
        return []
    files = []
    for name in sorted((n for n in os.listdir(LOG_DIR) if DETAIL_NAME.match(n)), reverse=True):
        path = os.path.join(LOG_DIR, name)
        files.append({'name': name, 'bytes': os.path.getsize(path),
                      'modified': datetime.fromtimestamp(os.path.getmtime(path)).strftime(TIME_FORMAT)})
    return files


def _remove_old_detail_files():
    for entry in detail_files()[DETAIL_KEEP_FILES:]:
        try:
            os.remove(os.path.join(LOG_DIR, entry['name']))
        except OSError:
            pass


def detail_file_path(name):
    """Path of a detail log file, None if the name is not a detail log file"""
    if not DETAIL_NAME.match(name or ''):
        return None
    path = os.path.join(LOG_DIR, name)
    return path if os.path.isfile(path) else None


def delete_detail_file(name):
    """Delete a detail log file that is not being written; returns True if deleted"""
    path = detail_file_path(name)
    if not path or path == _detail['path']:
        return False
    os.remove(path)
    return True


def detail_status():
    """State of the detail log for the user interface"""
    active = detail_active()
    return {
        'available': _enabled,
        'active': active,
        'file': os.path.basename(_detail['path']) if active else None,
        'scope': _detail['scope'] if active else None,
        'started': _detail['started'] if active else None,
        'until': datetime.fromtimestamp(_detail['until']).strftime(TIME_FORMAT) if active else None,
        'bytes': _detail['bytes'] if active else None,
        'last_stop_reason': _detail['stop_reason'],
        'max_bytes': MAX_BYTES,
        'keep_files': DETAIL_KEEP_FILES,
        'files': detail_files(),
    }
