from types import SimpleNamespace

from configsys import app, failures
from configsys.runner import Result

SIG_ERR = ("W: GPG error: https://pkg.jenkins.io/debian-stable binary/ Release: NO_PUBKEY "
           "7198F4B714ABFC68\nE: The repository 'https://pkg.jenkins.io/debian-stable binary/ "
           "Release' is not signed.")
JLIST = '/etc/apt/sources.list.d/jenkins.list'
KEY_URL = 'https://keyserver.ubuntu.com/pks/lookup?op=get&search=0x5E38...7198F4B714ABFC68'
KEY_PATH = '/usr/share/keyrings/jenkins-keyring.asc'


def _binding(**details):
    return SimpleNamespace(details=details)


def _ctx(components, runner=None):
    routes = SimpleNamespace(components=components)
    return SimpleNamespace(routes=routes, runner=runner)


def _jenkins_ctx(runner=None):
    jenkins = SimpleNamespace(bindings=[_binding(
        **{'source-path': JLIST, 'pubkey-url': KEY_URL, 'pubkey-path': KEY_PATH})])
    return _ctx({'jenkins': jenkins}, runner)


def test_source_key_fields_finds_the_binding():
    assert app._source_key_fields(_jenkins_ctx(), 'jenkins', JLIST) == (KEY_URL, KEY_PATH)


def test_source_key_fields_none_when_no_match():
    assert app._source_key_fields(_jenkins_ctx(), 'jenkins', '/etc/apt/sources.list.d/other.list') \
        == (None, None)


def test_rekey_candidates_managed_with_key():
    owned = {JLIST: 'jenkins'}
    finder = lambda urls, dirs: {JLIST: 'https://pkg.jenkins.io/debian-stable'}
    cands = app._rekey_candidates(_jenkins_ctx(), SIG_ERR, 'apt', owned, finder=finder)
    assert cands == [(JLIST, 'jenkins', KEY_URL, KEY_PATH)]


def test_rekey_candidates_skips_foreign():
    finder = lambda urls, dirs: {'/etc/apt/sources.list.d/rando.list': 'https://pkg.jenkins.io/debian-stable'}
    assert app._rekey_candidates(_jenkins_ctx(), SIG_ERR, 'apt', {}, finder=finder) == []


def test_rekey_candidates_only_signature_failures():
    owned = {JLIST: 'jenkins'}
    finder = lambda urls, dirs: {JLIST: 'x'}
    assert app._rekey_candidates(_jenkins_ctx(), 'Could not resolve host', 'apt', owned,
                                 finder=finder) == []


class _Runner:
    '''Records commands; apt-get update fails the FIRST time, succeeds after a key fetch.'''
    def __init__(self):
        self.cmds = []
        self.fetched = False

    def run(self, cmd, *, sudo=False, capture=True):
        self.cmds.append(cmd)
        if 'curl' in cmd:
            self.fetched = True
            return Result(cmd, 0)
        if 'apt-get update' in cmd:
            return Result(cmd, 0 if self.fetched else 1, stderr='' if self.fetched else SIG_ERR)
        return Result(cmd, 0)


def test_offer_rekey_prompts_refetches_and_heals(monkeypatch):
    r = _Runner()
    ctx = _jenkins_ctx(r)
    # inject the finder used inside _rekey_candidates via monkeypatching _find_source_files
    monkeypatch.setattr(app, '_find_source_files',
                        lambda urls, dirs: {JLIST: 'https://pkg.jenkins.io/debian-stable'})
    healed = app._offer_rekey(ctx, 'apt', SIG_ERR, {JLIST: 'jenkins'}, 'apt-get update',
                              ask=lambda prompt: True)
    assert healed is True
    assert r.fetched and any('curl' in c for c in r.cmds)


def test_offer_rekey_declined_does_nothing(monkeypatch):
    r = _Runner()
    monkeypatch.setattr(app, '_find_source_files',
                        lambda urls, dirs: {JLIST: 'https://pkg.jenkins.io/debian-stable'})
    healed = app._offer_rekey(_jenkins_ctx(r), 'apt', SIG_ERR, {JLIST: 'jenkins'}, 'apt-get update',
                              ask=lambda prompt: False)
    assert healed is False
    assert not any('curl' in c for c in r.cmds)   # never fetched when declined
