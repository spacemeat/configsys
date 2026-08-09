'''refreshstate — the last-refresh stamp the Components header reads for staleness.'''

import time

from configsys import refreshstate


class P:
    def __init__(self, tmp):
        self.state_dir = tmp
        self.last_refresh_file = tmp / 'last-refresh'


def test_never_then_record_then_age(tmp_path):
    p = P(tmp_path)
    assert refreshstate.age_days(p) is None            # never refreshed
    refreshstate.record(p)
    age = refreshstate.age_days(p)
    assert age is not None and 0.0 <= age < 1.0        # just now
    # a stamp from 40 days ago reads as ~40
    p.last_refresh_file.write_text(str(int(time.time()) - 40 * 86400))
    assert 39 < refreshstate.age_days(p) < 41


def test_garbage_stamp_reads_as_never(tmp_path):
    p = P(tmp_path)
    p.last_refresh_file.write_text('not-a-timestamp')
    assert refreshstate.age_days(p) is None
