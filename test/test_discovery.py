'''Project discovery — walk up from CWD to the nearest .configsys.hu / .configsys-*.hu,
auto-activate their profiles, tolerate a malformed one. The developer-in-source-tree path.'''

import os

from configsys import layers
from configsys.config import Config


def _w(p, text):
    p.write_text(text)
    return str(p)


def _config(tmp_path, user_text, discovered):
    up = _w(tmp_path / 'user.hu', user_text)
    roots = [('/no/config.hu', 'repo')] + [(d, 'discover') for d in discovered] + [(up, 'user')]
    return Config(layers.expand_tolerant(roots, {'discover'})[0])


# -- the walk + glob ------------------------------------------------------

def test_discover_walks_up_and_globs_base_first(tmp_path):
    proj = tmp_path / 'proj'
    (proj / 'src' / 'deep').mkdir(parents=True)
    _w(proj / '.configsys.hu', '{ profiles: { run: [ btop ] } }')
    _w(proj / '.configsys-dev.hu', '{ profiles: { build: [ gdb ] } }')
    found = layers.discover(str(proj / 'src' / 'deep'), home=str(tmp_path / 'elsewhere'))
    assert [os.path.basename(f) for f in found] == ['.configsys.hu', '.configsys-dev.hu']


def test_discover_stops_at_home(tmp_path):
    # a .configsys.hu sitting in $HOME is NOT a project (home is user-config territory)
    _w(tmp_path / '.configsys.hu', '{ profiles: { x: [ btop ] } }')
    assert layers.discover(str(tmp_path), home=str(tmp_path)) == []


def test_discover_none_when_absent(tmp_path):
    assert layers.discover(str(tmp_path), home=str(tmp_path / 'h')) == []


# -- auto-activation ------------------------------------------------------

def test_discovered_profiles_auto_activate_and_union(tmp_path):
    proj = tmp_path / 'proj'
    proj.mkdir()
    base = _w(proj / '.configsys.hu', '{ profiles: { run: [ btop ] } }')
    dev = _w(proj / '.configsys-dev.hu', '{ profiles: { build: [ gdb ] } }')
    c = _config(tmp_path, '{ configs: [ mine ]  profiles: { mine: [ ripgrep ] } }', [base, dev])
    assert set(c.active_profiles) == {'mine', 'run', 'build'}     # explicit + both discovered
    assert c.profile_components('build') == ['gdb']               # discovered def resolvable
    assert c.profile_source('build').endswith('.configsys-dev.hu')


def test_bundle_case_base_only(tmp_path):
    # only the base file present (as in a shipped bundle) -> only its profile activates
    proj = tmp_path / 'proj'
    proj.mkdir()
    base = _w(proj / '.configsys.hu', '{ profiles: { run: [ btop ] } }')
    c = _config(tmp_path, '{ configs: [ ] }', [base])
    assert c.active_profiles == ['run']


def test_ignore_profiles_suppresses_a_discovered_one(tmp_path):
    proj = tmp_path / 'proj'
    proj.mkdir()
    base = _w(proj / '.configsys.hu', '{ profiles: { run: [ btop ]  extra: [ gdb ] } }')
    c = _config(tmp_path, '{ configs: [ ]  ignore-profiles: [ extra ] }', [base])
    assert c.active_profiles == ['run']


# -- file-level resilience ------------------------------------------------

def test_malformed_discovered_file_is_skipped_not_fatal(tmp_path):
    # a parse/cycle failure in a discovered file is skipped with a warning; the rest loads
    proj = tmp_path / 'proj'
    proj.mkdir()
    _w(proj / '.configsys.hu', '{ profiles: { run: [ btop ] } }')
    bad = _w(proj / '.configsys-bad.hu', '{ include: [ ./missing.hu ] }')
    roots = [(str(proj / '.configsys.hu'), 'discover'), (bad, 'discover')]
    order, warnings = layers.expand_tolerant(roots, {'discover'})
    names = [os.path.basename(L.path) for L in order]
    assert '.configsys.hu' in names and '.configsys-bad.hu' not in names   # bad one skipped
    assert warnings and 'missing.hu' in warnings[0]
