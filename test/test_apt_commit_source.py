from configsys import failures
from configsys.drivers.apt import Apt
from configsys.runner import Result

XPATH = '/etc/apt/sources.list.d/x.list'
WRITE = f'if [ ! -f {XPATH} ]; then echo deb | sudo tee {XPATH} && sudo apt-get update; fi'
KEY_URL = 'https://keyserver.ubuntu.com/pks/lookup?op=get&search=0xDEADBEEF'
KEY_PATH = '/usr/share/keyrings/x.asc'
SIG = 'NO_PUBKEY 7198F4B714ABFC68'


class Runner:
    '''Scriptable + source-presence aware: `test -f`/`rm`/write track whether OUR source exists, and
    `apt-get update` fails only because of OUR source (unhealed key) — so removing it lets update
    recover, which is how _commit_source confirms ours was the culprit. `preexisting_break` instead
    models an UNRELATED broken source: update fails regardless of ours.'''
    def __init__(self, key_heals=True, preexisting_break=False):
        self.calls = []
        self.keyed = False
        self.key_heals = key_heals
        self.preexisting_break = preexisting_break
        self.present = False

    def run(self, cmd, *, sudo=False, capture=True):
        self.calls.append(cmd)
        if cmd.startswith('test -f'):
            return Result(cmd, 0 if self.present else 1)
        if 'curl' in cmd:
            self.keyed = True
            return Result(cmd, 0)
        if 'rm -f' in cmd:
            self.present = False
            return Result(cmd, 0)
        if 'tee' in cmd or 'echo deb' in cmd:           # the write_cmd creates our source
            self.present = True
        if 'apt-get update' in cmd:
            if self.preexisting_break:                  # unrelated broken source: never recovers
                return Result(cmd, 1, stderr='E: The list of sources could not be read.')
            broken = self.present and not (self.keyed and self.key_heals)   # only OUR source, unhealed
            return Result(cmd, 0 if not broken else 1, stderr='' if not broken else SIG)
        return Result(cmd, 0)


def test_rekey_heals_and_no_rollback():
    r = Runner(key_heals=True)
    res = Apt(r)._commit_source(WRITE, XPATH, KEY_URL, KEY_PATH)
    assert res is None                                  # healed by re-fetching the key
    assert r.keyed and any('curl' in c for c in r.calls)
    assert not any(c.startswith('sudo rm -f') for c in r.calls)   # nothing to roll back


def test_rollback_on_persistent_signature_failure():
    r = Runner(key_heals=False)                         # even a fresh key won't verify
    res = Apt(r)._commit_source(WRITE, XPATH, KEY_URL, KEY_PATH)
    assert res is not None and not res.ok
    assert res.category == failures.SIGNATURE
    assert any(c == f'sudo rm -f {XPATH}' for c in r.calls)   # our just-written source rolled back
    assert 'rolled back' in (res.stderr or '')


def test_preexisting_broken_source_restores_and_reports():
    # update fails on an UNRELATED pre-existing source; our source is valid. _commit_source must not
    # blame/roll back ours — it restores it and reports the real, pre-existing breakage.
    r = Runner(preexisting_break=True)
    res = Apt(r)._commit_source(WRITE, XPATH, KEY_URL, KEY_PATH)
    assert res is not None and not res.ok
    assert 'pre-existing apt source' in (res.stderr or '')
    assert 'rolled back' not in (res.stderr or '')
    assert r.present is True                              # our valid source was restored, not stranded


def test_no_key_configured_still_rolls_back():
    r = Runner(key_heals=False)
    res = Apt(r)._commit_source(WRITE, XPATH, None, None)
    assert res is not None and not res.ok
    assert not any('curl' in c for c in r.calls)        # no key to re-fetch
    assert any(c == f'sudo rm -f {XPATH}' for c in r.calls)


def test_success_first_try_is_clean():
    class OK:
        def __init__(self): self.calls = []
        def run(self, cmd, *, sudo=False, capture=True):
            self.calls.append(cmd)
            return Result(cmd, 1) if cmd.startswith('test -f') else Result(cmd, 0)
    r = OK()
    assert Apt(r)._commit_source(WRITE, XPATH, KEY_URL, KEY_PATH) is None
    assert not any('curl' in c or 'rm -f' in c for c in r.calls)
