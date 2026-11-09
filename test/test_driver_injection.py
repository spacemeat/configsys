'''A component name never reaches a shell unquoted (review-2026-11-2 tests-tools-16; the 2026-09
cross-driver gate): one name carrying shell metacharacters goes through EVERY built-in driver's
`install` and `uninstall` under a recording FakeRunner, and in every command it reaches the payload
stays inside one shell word. A driver that refuses the name outright (service's runit check) passes
too. It also makes sure each driver's install/uninstall is actually driven by a test, not just
imported: a driver whose ops build no command from a bare name (it needs a download url, content
root or declared commands first) is listed in SHALLOW with why.'''

import shlex

import pytest

from configsys.componentObj import ResolvedComponent
from configsys.drivers import BUILTIN_DRIVERS, _REGISTRY
from configsys.paths import Paths

from fakes import FakeRunner

BAD = 'x;touch${IFS}/tmp/pwn'

# install builds no command from a name alone — it needs more of the binding
SHALLOW = {
    'appImage': 'install needs a download url',
    'aur': 'install needs the AUR helper / makepkg sources resolved first',
    'dotfiles': 'install links content from a store root; no shell command',
    'font': 'install needs a download url',
    'glue': 'install links shipped snippets; no shell command',
    'native-pkg-file': 'install needs a release asset url',
    'script': 'install runs the binding\'s declared commands, not the name',
    'source': 'install needs a git/archive source',
    'tarball': 'install needs a download url',
}


def _unquoted(cmd):
    '''True when BAD appears in `cmd` outside a single shell word (a `;` that would split it).'''
    try:
        lex = shlex.shlex(cmd, posix=True, punctuation_chars=True)
        lex.whitespace_split = True
        words = list(lex)
    except ValueError:                                  # unbalanced quoting: can't vouch for it
        return True
    return sum(w.count(BAD) for w in words) != cmd.count(BAD)


@pytest.mark.parametrize('name', sorted(BUILTIN_DRIVERS))
def test_install_and_uninstall_keep_a_hostile_name_in_one_shell_word(name, tmp_path):
    runner = FakeRunner()
    paths = Paths(env={'CONFIGSYS_HOME': str(tmp_path)})
    rc = ResolvedComponent(key=f'{name}\\{BAD}', driver=name, comp=BAD, fields={'name': BAD})
    calls, refused = {}, []
    for op in ('install', 'uninstall'):
        before = len(runner.calls)
        try:
            getattr(_REGISTRY[name](runner, paths), op)(rc)
        except ValueError as e:                         # refused the unsafe name before any command
            assert 'unsafe' in str(e), e
            refused.append(op)
        calls[op] = runner.calls[before:]
    leaks = [c for c in runner.calls if BAD in c and _unquoted(c)]
    assert not leaks, f'{name}: the name reached a shell unquoted: {leaks}'
    exercised = bool(calls['install']) or 'install' in refused
    assert exercised or name in SHALLOW, \
        f'{name}: install ran no command for a bare name — test it, or list it in SHALLOW with why'
    if name in SHALLOW:
        assert not calls['install'], f'{name} builds an install command now — drop it from SHALLOW'


def test_the_quoting_check_catches_a_bare_name():
    assert _unquoted(f'apt-get install -y {BAD}')
    assert not _unquoted(f'apt-get install -y {shlex.quote(BAD)}')
    assert not _unquoted(f"dnf install -y 'gcc-toolset-{BAD}'")
