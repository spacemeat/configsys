'''Transport edge cases: private-repo auth (ssh / full-URL passthrough + CONFIGSYS_GIT_TOKEN)
and checksum verification of a synced plugin against a declared `sha256` (belt-and-suspenders
beyond ref pinning — quarantines a moved tag / compromised mirror / tampered tree).'''

import shutil
import subprocess

import pytest

from configsys import plugins
from configsys.runner import Result

pytestmark = pytest.mark.real_runner  # real git clones/commits in tmp dirs (conftest)


# -- non-interactive fetches (a bad/private repo fails fast, never hangs on a prompt) ------

def test_noninteractive_git_env_disables_prompts():
    env = plugins._noninteractive_git_env()
    assert env['GIT_TERMINAL_PROMPT'] == '0'    # git's own "Username:" terminal prompt
    assert env['GCM_INTERACTIVE'] == 'never'    # git-credential-manager's prompt
    assert 'PATH' in env                         # inherits the ambient env, doesn't replace it


class _RecRunner:
    '''Records (cmd, env) per run and reports success — enough to walk _git_transport.'''
    def __init__(self):
        self.calls = []

    def run(self, cmd, *, sudo=False, capture=True, tui_active=None, cwd=None, env=None):
        self.calls.append((cmd, env))
        return Result(cmd, 0, stdout='deadbeef')   # rev-parse/checkout/clone all "ok"


def test_git_transport_clone_and_fetch_pass_noninteractive_env(tmp_path):
    r = _RecRunner()
    dest = tmp_path / 'plugins' / 'p'
    plugins._git_transport(r, dest, 'github:me/p', 'v1')          # dest absent -> clone path
    clone = next((env for cmd, env in r.calls if 'git clone' in cmd), None)
    assert clone is not None and clone['GIT_TERMINAL_PROMPT'] == '0'

    dest.mkdir(parents=True, exist_ok=True)
    r2 = _RecRunner()
    plugins._git_transport(r2, dest, 'github:me/p', 'v1')          # dest present -> fetch path
    fetch = next((env for cmd, env in r2.calls if 'git -C' in cmd and 'fetch' in cmd), None)
    assert fetch is not None and fetch['GIT_TERMINAL_PROMPT'] == '0'


# -- private-repo auth ----------------------------------------------------

def test_source_url_passthrough_for_ssh_and_full_urls():
    assert plugins.source_url('git@github.com:me/p.git') == 'git@github.com:me/p.git'
    assert plugins.source_url('https://user:tok@host/p.git') == 'https://user:tok@host/p.git'
    assert plugins.source_url('/local/p') == '/local/p'


def test_the_token_rides_a_header_never_the_url(monkeypatch):
    # review-2026-11-2 plugins-07: an embedded token leaked into the command log, `--pretend`
    # output and .git/config — it goes to git as an http.<host>.extraheader in the env instead
    import base64
    monkeypatch.setenv('CONFIGSYS_GIT_TOKEN', 'sekrit')
    monkeypatch.setenv('GIT_CONFIG_COUNT', '1')                       # one of the user's own: kept
    monkeypatch.setenv('GIT_CONFIG_KEY_0', 'core.mine')
    monkeypatch.setenv('GIT_CONFIG_VALUE_0', 'x')
    assert plugins.clone_url('github:me/p') == 'https://github.com/me/p.git'
    assert plugins.clone_url('gitlab:me/p') == 'https://gitlab.com/me/p.git'
    assert plugins.clone_url('git@host:me/p.git') == 'git@host:me/p.git'
    env = plugins._noninteractive_git_env()
    assert env['GIT_CONFIG_COUNT'] == '3' and env['GIT_CONFIG_KEY_0'] == 'core.mine'
    headers = {env[f'GIT_CONFIG_KEY_{i}']: env[f'GIT_CONFIG_VALUE_{i}'] for i in (1, 2)}
    gh = headers['http.https://github.com/.extraheader']
    gl = headers['http.https://gitlab.com/.extraheader']
    assert base64.b64decode(gh.split()[-1]).decode() == 'x-access-token:sekrit'
    assert base64.b64decode(gl.split()[-1]).decode() == 'oauth2:sekrit'


def test_a_pretend_sync_shows_no_token(monkeypatch, tmp_path):
    from configsys.runner import Runner
    monkeypatch.setenv('CONFIGSYS_GIT_TOKEN', 'sekrit')
    echoed = []
    r = Runner(pretend=True, echo=echoed.append)
    plugins._git_transport(r, tmp_path / 'plugins' / 'p', 'github:me/p', 'v1')
    assert r.calls and not any('sekrit' in c for c in r.calls + echoed)
    r.run('git clone -- https://user:pw@host/p.git /x')                 # a URL you wrote yourself
    assert r.calls[-1] == 'git clone -- https://***@host/p.git /x' and 'pw' not in echoed[-1]


def test_clone_url_without_token_is_plain(monkeypatch):
    monkeypatch.delenv('CONFIGSYS_GIT_TOKEN', raising=False)
    assert plugins.clone_url('github:me/p') == 'https://github.com/me/p.git'


# -- ssh push url (author over ssh keys while fetching over https) ---------

def test_ssh_url_for_shorthands():
    assert plugins.ssh_url('github:me/p') == 'git@github.com:me/p.git'
    assert plugins.ssh_url('gitlab:me/p.git') == 'git@gitlab.com:me/p.git'   # keeps a present .git
    assert plugins.ssh_url('git@github.com:me/p.git') is None                # already ssh
    assert plugins.ssh_url('https://github.com/me/p.git') is None            # full url — leave it
    assert plugins.ssh_url('/local/p') is None


@pytest.mark.skipif(shutil.which('git') is None, reason='git not available')
def test_set_push_remote_gives_ssh_pushurl_but_keeps_https_fetch(tmp_path):
    repo = tmp_path / 'r'; repo.mkdir()
    subprocess.run(['git', '-C', str(repo), 'init', '-q'], check=True)
    subprocess.run(['git', '-C', str(repo), 'remote', 'add', 'origin',
                    'https://github.com/me/p.git'], check=True)
    from configsys.runner import Runner
    plugins._set_push_remote(Runner(pretend=False), repo, 'github:me/p')

    def _url(*extra):
        return subprocess.run(['git', '-C', str(repo), 'remote', 'get-url', *extra, 'origin'],
                              capture_output=True, text=True).stdout.strip()
    assert _url('--push') == 'git@github.com:me/p.git'   # push over ssh
    assert _url() == 'https://github.com/me/p.git'       # fetch stays https

    # a re-sync with only_if_unset must NOT clobber a push url the user set by hand
    subprocess.run(['git', '-C', str(repo), 'remote', 'set-url', '--push', 'origin',
                    'https://github.com/me/p.git'], check=True)
    plugins._set_push_remote(Runner(pretend=False), repo, 'github:me/p', only_if_unset=True)
    assert _url('--push') == 'https://github.com/me/p.git'   # left the user's choice alone


# -- checksum verification ------------------------------------------------

def _data_plugin(pd, name):
    d = pd / name
    d.mkdir(parents=True)
    (d / 'plugin.hu').write_text(f'{{ name: {name}  requires-abi: 1  data: [ r.hu ] }}')
    (d / 'r.hu').write_text('{ components: { c: { install: [ { via: native } ] } } }')
    return d


def test_checksum_ok_variants(tmp_path):
    pd = tmp_path / 'plugins'
    d = _data_plugin(pd, 'p')
    ident = plugins.plugin_identity(d)
    src = {'source': 'github:x/p'}
    assert plugins.checksum_ok(pd, src)                                   # no sha256 -> ok
    assert plugins.checksum_ok(pd, {**src, 'sha256': ident})             # exact
    assert plugins.checksum_ok(pd, {**src, 'sha256': ident.split(':')[-1]})  # bare hex accepted
    assert not plugins.checksum_ok(pd, {**src, 'sha256': 'sha256:deadbeef'})
    (d / 'r.hu').write_text('{ components: { tampered: {} } }')          # edit a file
    assert not plugins.checksum_ok(pd, {**src, 'sha256': ident})


def test_layer_files_quarantines_a_mismatch(tmp_path):
    pd = tmp_path / 'plugins'
    d = _data_plugin(pd, 'p')
    good = {'source': 'github:x/p', 'sha256': plugins.plugin_identity(d)}
    assert plugins.layer_files(pd, [good])                               # verified -> included
    bad = {'source': 'github:x/p', 'sha256': 'sha256:00'}
    assert plugins.layer_files(pd, [bad]) == []                          # mismatch -> excluded


def test_load_code_quarantines_a_mismatch(tmp_path):
    pd = tmp_path / 'plugins'
    d = pd / 'p'
    d.mkdir(parents=True)
    (d / 'plugin.hu').write_text('{ name: p  requires-abi: 1  code: c.py }')
    (d / 'c.py').write_text('DRIVERS = []\n')
    tf = tmp_path / 'trust.hu'
    plugins.set_trust(tf, 'p', plugins.plugin_identity(d))               # trusted content...
    decls = [{'source': 'github:x/p', 'sha256': 'sha256:00'}]           # ...but wrong checksum
    loaded, skipped = plugins.load_code(pd, tf, decls, lambda c: None)
    assert loaded == []
    assert 'does not match declared sha256' in dict(skipped)['p']


# -- the pin lifecycle through the CLI (needs git: add clones) ------------

@pytest.mark.skipif(shutil.which('git') is None, reason='git not available')
def test_add_pin_then_tamper_is_quarantined(tmp_path, capsys):
    from configsys.app import main
    src = tmp_path / 'src'
    src.mkdir()
    (src / 'plugin.hu').write_text('{ name: pp  requires-abi: 1  data: [ r.hu ] }')
    (src / 'r.hu').write_text('{ components: { ptool: { install: [ { via: native } ] } } }')
    for cmd in (['init', '-q'], ['config', 'user.email', 't@t'], ['config', 'user.name', 't'],
                ['add', '-A'], ['commit', '-qm', 'i']):
        subprocess.run(['git', *cmd], cwd=src, check=True)
    home = ['--home', str(tmp_path), '--os', 'pop']

    assert main(home + ['plugin', 'add', str(src), '--pin']) == 0
    assert 'pinned pp @' in capsys.readouterr().out
    cfg = (tmp_path / '.config' / 'configsys' / 'configsys.hu').read_text()
    assert 'sha256:' in cfg                                               # locked in the config

    # tamper with the synced tree -> list + check both flag the quarantine
    synced = tmp_path / '.config' / 'configsys' / 'plugins' / 'src' / 'r.hu'
    synced.write_text('{ components: { evil: { install: [ { via: native } ] } } }')

    main(home + ['plugin', 'list'])
    assert 'CHECKSUM MISMATCH' in capsys.readouterr().out
    main(home + ['check'])
    assert 'does not match declared sha256' in capsys.readouterr().out
