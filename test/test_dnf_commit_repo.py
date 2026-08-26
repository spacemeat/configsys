from configsys import failures
from configsys.drivers.dnf import Dnf
from configsys.runner import Result

RID = 'vendor'
CONTENT = f'[{RID}]\nname=Vendor\nbaseurl=https://ex.com/repo\nenabled=1\ngpgcheck=1\ngpgkey=https://ex.com/k\n'
REPO = f'/etc/yum.repos.d/{RID}.repo'


class Runner:
    def __init__(self, exists=False, makecache_ok=True):
        self.calls = []
        self._exists = exists
        self._mc_ok = makecache_ok

    def run(self, cmd, *, sudo=False, capture=True):
        self.calls.append(cmd)
        if cmd.startswith('test -f'):
            return Result(cmd, 0 if self._exists else 1)
        if 'makecache' in cmd:
            return Result(cmd, 0 if self._mc_ok else 1,
                          stderr='' if self._mc_ok else 'Cannot download repomd.xml: Curl error (6)')
        return Result(cmd, 0)


def test_new_repo_validates_and_passes():
    r = Runner(exists=False, makecache_ok=True)
    assert Dnf(r)._commit_repo(CONTENT, RID) is None
    assert any('makecache' in c for c in r.calls)
    assert not any('rm -f' in c for c in r.calls)


def test_new_repo_rolls_back_on_refresh_failure():
    r = Runner(exists=False, makecache_ok=False)
    res = Dnf(r)._commit_repo(CONTENT, RID)
    assert res is not None and not res.ok
    assert res.category == failures.NETWORK          # "Cannot download" -> network class
    assert any(c == f'sudo rm -f {REPO}' for c in r.calls)
    assert 'rolled back' in (res.stderr or '')


def test_existing_repo_is_not_revalidated():
    r = Runner(exists=True, makecache_ok=False)      # would fail IF it validated
    assert Dnf(r)._commit_repo(CONTENT, RID) is None
    assert not any('makecache' in c for c in r.calls)   # skipped: it worked before
    assert not any('rm -f' in c for c in r.calls)
