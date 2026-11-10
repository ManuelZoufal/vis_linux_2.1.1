"""
Thread-safe registry for the status of the background threads.

Each background thread is registered once and then reports the result of
every cycle. The registry is read by /api/thread_status for the live view.
"""
import threading
from datetime import datetime

TIME_FORMAT = '%Y-%m-%d %H:%M:%S'

# A thread counts as unresponsive if it has not reported for this long
STALE_FACTOR = 3        # ... times its interval
STALE_MIN_SECONDS = 30  # ... but at least this many seconds

_lock = threading.Lock()
_entries = {}  # name -> dict, in registration order


def register(name, label=None, interval=None):
    """
    Register a background thread before it is started

    Args:
    name (str): Name of the thread (must equal threading.Thread.name)
    label (str, optional): Text shown in the user interface
    interval (int, optional): Expected seconds between two cycles
    """
    with _lock:
        _entries[name] = {
            'name': name,
            'label': label or name,
            'interval': interval,
            'thread': None,
            'started_at': None,
            'ended': False,
            'last_result': None,  # None | 'ok' | 'error'
            'last_run': None,
            'last_success': None,
            'last_error': None,
            'last_error_time': None,
            'detail': None,
            'run_count': 0,
            'error_count': 0,
        }


def _current_entry():
    return _entries.get(threading.current_thread().name)


def bind():
    """Mark the calling thread as started"""
    with _lock:
        entry = _current_entry()
        if entry:
            entry['thread'] = threading.current_thread()
            entry['started_at'] = datetime.now()
            entry['ended'] = False


def report_success(detail=None):
    """
    Report a successful cycle of the calling thread

    Args:
    detail (str, optional): Additional information shown in the user interface
    """
    with _lock:
        entry = _current_entry()
        if entry:
            now = datetime.now()
            entry['last_result'] = 'ok'
            entry['last_run'] = now
            entry['last_success'] = now
            entry['detail'] = detail
            entry['run_count'] += 1


def report_error(error):
    """
    Report a failed cycle of the calling thread

    Args:
    error (str): Description of the error
    """
    with _lock:
        entry = _current_entry()
        if entry:
            now = datetime.now()
            entry['last_result'] = 'error'
            entry['last_run'] = now
            entry['last_error'] = str(error)
            entry['last_error_time'] = now
            entry['run_count'] += 1
            entry['error_count'] += 1


def report_ended(error=None):
    """
    Report that the calling thread has left its target function

    Args:
    error (str, optional): Description of the error that ended the thread
    """
    with _lock:
        entry = _current_entry()
        if entry:
            entry['ended'] = True
            if error:
                entry['last_error'] = str(error)
                entry['last_error_time'] = datetime.now()
                entry['error_count'] += 1


def _format(moment):
    return moment.strftime(TIME_FORMAT) if moment else None


def _state(entry, now):
    thread = entry['thread']
    if thread is None:
        return 'not_started'
    if entry['ended'] or not thread.is_alive():
        return 'stopped'
    reference = entry['last_run'] or entry['started_at']
    if entry['interval'] is not None:
        limit = max(STALE_FACTOR * entry['interval'], STALE_MIN_SECONDS)
        if (now - reference).total_seconds() > limit:
            return 'stale'
    if entry['last_result'] is None:
        return 'starting'
    return entry['last_result']


def snapshot():
    """
    Get the current status of all registered threads

    Returns:
    list: One dict per thread, in registration order
    """
    now = datetime.now()
    with _lock:
        result = []
        for entry in _entries.values():
            reference = entry['last_run'] or entry['started_at']
            result.append({
                'name': entry['name'],
                'label': entry['label'],
                'state': _state(entry, now),
                'interval': entry['interval'],
                'started_at': _format(entry['started_at']),
                'last_run': _format(entry['last_run']),
                'last_success': _format(entry['last_success']),
                'last_error': entry['last_error'],
                'last_error_time': _format(entry['last_error_time']),
                'detail': entry['detail'],
                'run_count': entry['run_count'],
                'error_count': entry['error_count'],
                'seconds_since_last_run': int((now - reference).total_seconds()) if reference else None,
            })
        return result
