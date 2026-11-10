"""
Protection against password guessing on the login page

Failed logins are counted in memory per (client address, user name) and per
client address. After too many failures within the time window further
attempts are rejected until the window has passed. A successful login
clears the counter of that user name for that client.
"""
import os
import threading
import time

MAX_ATTEMPTS = int(os.environ.get('LOGIN_MAX_ATTEMPTS', 5))        # per client and user name
LOCK_MINUTES = int(os.environ.get('LOGIN_LOCK_MINUTES', 15))       # window and lock duration
MAX_ATTEMPTS_PER_CLIENT = MAX_ATTEMPTS * 4                         # per client, any user name
MAX_TRACKED_KEYS = 10000                                           # memory bound

_lock = threading.Lock()
_failures = {}  # key -> list of timestamps of failed attempts


def _keys(client, username):
    return (('pair', client, username.strip().lower()), ('client', client))


def _limit(key):
    return MAX_ATTEMPTS if key[0] == 'pair' else MAX_ATTEMPTS_PER_CLIENT


def _recent(key, now):
    """Failed attempts of this key within the window (expired ones are dropped)"""
    window = LOCK_MINUTES * 60
    attempts = [t for t in _failures.get(key, ()) if now - t < window]
    if attempts:
        _failures[key] = attempts
    else:
        _failures.pop(key, None)
    return attempts


def seconds_locked(client, username):
    """
    Check whether a login attempt is currently blocked

    Returns:
    int: Seconds until the next attempt is allowed, 0 if not blocked
    """
    now = time.time()
    remaining = 0
    with _lock:
        for key in _keys(client, username):
            attempts = _recent(key, now)
            if len(attempts) >= _limit(key):
                # blocked until the oldest counted failure leaves the window
                remaining = max(remaining, int(LOCK_MINUTES * 60 - (now - attempts[0])) + 1)
    return remaining


def record_failure(client, username):
    """
    Count a failed login

    Returns:
    bool: True if this failure triggered the lock
    """
    now = time.time()
    triggered = False
    with _lock:
        if len(_failures) > MAX_TRACKED_KEYS:
            for key in list(_failures):
                _recent(key, now)
        for key in _keys(client, username):
            attempts = _recent(key, now)
            attempts.append(now)
            _failures[key] = attempts
            if len(attempts) == _limit(key):
                triggered = True
    return triggered


def record_success(client, username):
    """Forget the failed attempts of this user name from this client"""
    with _lock:
        _failures.pop(_keys(client, username)[0], None)
