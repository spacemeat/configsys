from configsys import failures
from configsys.drivers.apt import Apt
from configsys.runner import Result

XPATH = '/etc/apt/sources.list.d/x.list'
WRITE = f'if [ ! -f {XPATH} ]; then echo deb | sudo tee {XPATH} && sudo apt-get update; fi'
KEY_URL = 'https://keyserver.ubuntu.com/pks/lookup?op=get&search=0xDEADBEEF'
KEY_PATH = '/usr/share/keyrings/x.asc'
SIG = 'NO_PUBKEY 7198F4B714ABFC68'


class Runner:
    '''Scriptable: `test -f` reports absent; apt-get update fails until a key is (re-)fetched.'''
    def __init__(self, key_heals=True):
        self.calls = []
        self.keyed = False
        self.key_heals = key_heals

    def run(self, cmd, *, sudo=False, capture=True):
        self.calls.append(cmd)
        if cmd.startswith('test -f'):
            return Result(cmd, 1)                       # source not present yet
        if 'curl' in cmd:
            self.keyed = True
            return Result(cmd, 0)
        if 'apt-get update' in cmd:
            ok = self.keyed and self.key_heals
            return Result(cmd, 0 if ok else 1, stderr='' if ok else SIG)
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
