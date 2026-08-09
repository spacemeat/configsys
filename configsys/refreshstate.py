'''refreshstate.py — a one-line stamp of when `configsys refresh` last ran, so the TUI can show
how stale the package view is. Just a unix timestamp in <state>/last-refresh; missing = never.'''

import time


def record(paths):
    '''Stamp "now" as the last refresh. Best-effort — a write failure is not fatal.'''
    try:
        paths.state_dir.mkdir(parents=True, exist_ok=True)
        paths.last_refresh_file.write_text(str(int(time.time())), encoding='utf-8')
    except OSError:
        pass


def age_days(paths):
    '''Days since the last refresh (float, >= 0), or None if never run / unreadable.'''
    try:
        ts = int(paths.last_refresh_file.read_text(encoding='utf-8').strip())
    except (OSError, ValueError):
        return None
    return max(0.0, (time.time() - ts) / 86400.0)
