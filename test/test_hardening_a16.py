'''review-2026-11-2 A16 — misc hardening: a private AUR build dir and a validated name; `--home` is a
full sandbox (children get HOME=<sandbox>, inherited state/config/XDG paths dropped); the report
scrubber masks URL credentials and common token shapes.'''

import pytest

from configsys.componentObj import ResolvedComponent
from configsys.runner import Runner


def test_aur_builds_in_a_private_dir_and_refuses_a_path_name():
    from configsys.drivers.aur import Aur
    r = Runner(pretend=True)
    a = Aur(r)
    a.install(ResolvedComponent(key='aur\\yay-bin', driver='aur', comp='yay-bin', fields={'name': 'yay-bin'}))
    assert 'mktemp -d' in r.calls[-1] and '/tmp/configsys-aur/' not in r.calls[-1]
    bad = a.install(ResolvedComponent(key='aur\\x', driver='aur', comp='x', fields={'name': '../../home/victim'}))
    assert not bad.ok and len(r.calls) == 1


def test_home_is_a_full_sandbox(tmp_path, monkeypatch):
    from configsys.app import Context, build_parser
    monkeypatch.setenv('CONFIGSYS_STATE_DIR', str(tmp_path / 'REAL-state'))
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path / 'REAL-config'))
    box = tmp_path / 'box'
    ctx = Context(build_parser().parse_args(['--home', str(box), '--os', 'pop_os!:24.04', 'inspect']))
    assert str(ctx.paths.state_dir).startswith(str(box))
    assert str(ctx.paths.user_config_file).startswith(str(box))
    from configsys.runner import sandboxed_env
    env = sandboxed_env({'HOME': '/home/real', 'XDG_DATA_HOME': '/x', 'PATH': '/bin'}, box)
    assert env == {'HOME': str(box), 'PATH': '/bin'}
    assert ctx.runner.sandbox_home == str(box)


@pytest.mark.real_runner
def test_a_sandboxed_runner_gives_children_the_sandbox_home(tmp_path):
    r = Runner(sandbox_home=tmp_path)
    res = r.run('echo "$HOME"')
    assert res.stdout.strip() == str(tmp_path)


@pytest.mark.parametrize('line, leak', [
    ('git clone https://oauth2:glpat-AbCdEf0123456789xyz@gitlab.com/me/p.git', 'glpat-AbCdEf'),
    ('pip install --index-url https://alice:s3cr3tpw@pypi.corp.example/simple foo', 's3cr3tpw'),
    ('export NPM_TOKEN=npm_AbCdEf0123456789AbCdEf0123456789ab', 'npm_AbCd'),
    ('Bearer-less eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abcdefghijklmnop', 'eyJhbGci')])
def test_the_report_scrubber_masks_more_secret_shapes(line, leak):
    from configsys.reportgen import scrub
    assert leak not in scrub(line)
