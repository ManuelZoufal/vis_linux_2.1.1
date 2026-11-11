"""
Verbose server log for a limited time

In normal operation the server log only contains the start, warnings and
errors. An administrator can switch on the verbose output (every sensor
query, every web request, messages of the libraries) for a chosen time
without a restart. It switches itself off again.

This only changes log levels. It does not enable the Werkzeug debugger,
which stays bound to APP_DEBUG in .env.
"""
import logging
import threading
import time
from datetime import datetime

from src import event_log

TIME_FORMAT = '%Y-%m-%d %H:%M:%S'

_lock = threading.Lock()
_state = {'always': False, 'until': 0.0, 'started': None, 'timer': None, 'last_stop_reason': None}
_base = {'root': logging.INFO, 'werkzeug': logging.WARNING}


def init(app_debug):
    """
    Remember the log levels of normal operation; called once at startup

    Args:
    app_debug (bool): True if APP_DEBUG is set, the log is then always verbose
    """
    _state['always'] = bool(app_debug)
    _base['root'] = logging.getLogger().level
    _base['werkzeug'] = logging.getLogger('werkzeug').level


def _apply(verbose):
    logging.getLogger().setLevel(logging.DEBUG if verbose else _base['root'])
    logging.getLogger('werkzeug').setLevel(logging.INFO if verbose else _base['werkzeug'])


def _stop_locked(reason):
    if not _state['until']:
        return False
    if _state['timer']:
        _state['timer'].cancel()
    _state.update(until=0.0, started=None, timer=None, last_stop_reason=reason)
    _apply(False)
    return True


def _expire(expected_until):
    with _lock:
        if _state['until'] != expected_until:
            return  # replaced or stopped in the meantime
        stopped = _stop_locked('Zeit abgelaufen')
    if stopped:
        logging.info("[VIS] Ausführliches Server-Log beendet (Zeit abgelaufen)")
        event_log.event('info', 'ServerLog', "Ausführliches Server-Log beendet (Zeit abgelaufen)", 'Server-Log')


def start(seconds):
    """
    Switch the verbose server log on for a limited time; a running period is replaced

    Args:
    seconds (int): Duration

    Returns:
    str: Time at which it switches itself off
    """
    with _lock:
        _stop_locked('durch neuen Zeitraum ersetzt')
        until = time.time() + seconds
        timer = threading.Timer(seconds, _expire, args=(until,))
        timer.daemon = True
        _state.update(until=until, started=datetime.now().strftime(TIME_FORMAT), timer=timer, last_stop_reason=None)
        _apply(True)
        timer.start()
    until_text = datetime.fromtimestamp(until).strftime(TIME_FORMAT)
    logging.info(f"[VIS] Ausführliches Server-Log eingeschaltet bis {until_text}")
    event_log.event('info', 'ServerLog', f"Ausführliches Server-Log eingeschaltet bis {until_text}", 'Server-Log')
    return until_text


def stop(reason='manuell beendet'):
    """Switch the verbose server log off; returns True if it was running"""
    with _lock:
        stopped = _stop_locked(reason)
    if stopped:
        logging.info(f"[VIS] Ausführliches Server-Log beendet ({reason})")
        event_log.event('info', 'ServerLog', f"Ausführliches Server-Log beendet ({reason})", 'Server-Log')
    return stopped


def status():
    """State of the verbose server log for the user interface"""
    with _lock:
        active = bool(_state['until']) and time.time() < _state['until']
        return {
            'always': _state['always'],
            'active': active,
            'started': _state['started'] if active else None,
            'until': datetime.fromtimestamp(_state['until']).strftime(TIME_FORMAT) if active else None,
            'last_stop_reason': _state['last_stop_reason'],
        }
