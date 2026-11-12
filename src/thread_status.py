"""
Thread-safe registry for the status of the background threads.

Each background thread is registered once and then reports the result of
every cycle. The registry is read by /api/thread_status for the live view.
"""
import threading
from datetime import datetime

from src import event_log

TIME_FORMAT = '%Y-%m-%d %H:%M:%S'

# A thread counts as unresponsive if it has not reported for this long
STALE_FACTOR = 3        # ... times its interval
STALE_MIN_SECONDS = 30  # ... but at least this many seconds

# While a thread keeps failing, the event log gets a reminder at most this often
REMINDER_SECONDS = 3600
MAX_ERROR_LENGTH = 300

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
            'streak_count': 0,      # consecutive failures
            'streak_started': None,
            'streak_logged': None,  # time of the last event log entry of this streak
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


def _duration(seconds):
    seconds = int(seconds)
    if seconds < 120:
        return f"{seconds} s"
    if seconds < 7200:
        return f"{seconds // 60} min"
    return f"{seconds // 3600} h {seconds % 3600 // 60} min"


def report_success(detail=None):
    """
    Report a successful cycle of the calling thread

    Args:
    detail (str, optional): Additional information shown in the user interface
    """
    recovered = None
    with _lock:
        entry = _current_entry()
        if entry:
            now = datetime.now()
            if entry['streak_count'] and entry['streak_logged']:
                recovered = (entry['name'], entry['label'],
                             f"Wieder OK nach {entry['streak_count']} Fehlversuch(en), Ausfall seit "
                             f"{_format(entry['streak_started'])} ({_duration((now - entry['streak_started']).total_seconds())})")
            entry['streak_count'] = 0
            entry['streak_started'] = None
            entry['streak_logged'] = None
            entry['last_result'] = 'ok'
            entry['last_run'] = now
            entry['last_success'] = now
            entry['detail'] = detail
            entry['run_count'] += 1
    if recovered:
        event_log.event('recovered', recovered[0], recovered[2], recovered[1])


def report_idle(detail=None):
    """
    Report a cycle in which the calling thread had nothing to do on purpose
    (e.g. a sensor that is not used for counting). Ends a series of failures
    without a recovery entry in the event log.

    Args:
    detail (str, optional): Additional information shown in the user interface
    """
    with _lock:
        entry = _current_entry()
        if entry:
            entry['streak_count'] = 0
            entry['streak_started'] = None
            entry['streak_logged'] = None
            entry['last_result'] = 'idle'
            entry['last_run'] = datetime.now()
            entry['detail'] = detail


def report_error(error, log_event=True):
    """
    Report a failed cycle of the calling thread

    The first failure of a series is written to the event log, further ones
    only as a reminder once per REMINDER_SECONDS, the recovery again.

    Args:
    error (str): Description of the error
    log_event (bool): False if the caller writes its own event log entry
    """
    logged = None
    with _lock:
        entry = _current_entry()
        if entry:
            now = datetime.now()
            message = event_log.shorten(error, MAX_ERROR_LENGTH)
            entry['last_result'] = 'error'
            entry['last_run'] = now
            entry['last_error'] = message
            entry['last_error_time'] = now
            entry['run_count'] += 1
            entry['error_count'] += 1
            if log_event:
                entry['streak_count'] += 1
                if entry['streak_started'] is None:
                    entry['streak_started'] = now
                    entry['streak_logged'] = now
                    logged = ('error', entry['name'], entry['label'], message)
                elif (now - entry['streak_logged']).total_seconds() >= REMINDER_SECONDS:
                    entry['streak_logged'] = now
                    logged = ('ongoing', entry['name'], entry['label'],
                              f"Weiterhin Fehler: {entry['streak_count']} Fehlversuche seit {_format(entry['streak_started'])}. Zuletzt: {message}")
    if logged:
        event_log.event(logged[0], logged[1], logged[3], logged[2])


def report_ended(error=None):
    """
    Report that the calling thread has left its target function

    Args:
    error (str, optional): Description of the error that ended the thread
    """
    ended = None
    with _lock:
        entry = _current_entry()
        if entry:
            entry['ended'] = True
            if error:
                entry['last_error'] = event_log.shorten(error, MAX_ERROR_LENGTH)
                entry['last_error_time'] = datetime.now()
                entry['error_count'] += 1
            ended = (entry['name'], entry['label'],
                     f"Thread beendet: {event_log.shorten(error, MAX_ERROR_LENGTH)}" if error else "Thread beendet")
    if ended:
        event_log.event('ended', ended[0], ended[2], ended[1])


def fault_seconds(name):
    """
    How long a thread has been failing without interruption

    Counts a series of failed cycles, a thread that ended and a thread that
    stopped reporting. A thread that idles on purpose is not failing.

    Args:
    name (str): Name of the thread

    Returns:
    float: Seconds since the failure began, 0 if the thread works or is unknown
    """
    now = datetime.now()
    with _lock:
        entry = _entries.get(name)
        if not entry:
            return 0
        if entry['streak_started']:
            return (now - entry['streak_started']).total_seconds()
        state = _state(entry, now)
        reference = entry['last_run'] or entry['started_at']
        if state in ('stopped', 'stale') and reference:
            return (now - reference).total_seconds()
        if state == 'error' and entry['last_error_time']:
            return (now - (entry['last_success'] or entry['started_at'] or entry['last_error_time'])).total_seconds()
        return 0


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
