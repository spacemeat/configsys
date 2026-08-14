'''`latest-check:` — an ADVISORY upstream-version check for manual (`static:`) version pins.
`refresh` fetches the latest-check source, compares to the pin, and stamps the ones behind upstream;
`check` re-surfaces them from the stamp (no network). Nothing auto-bumps — it just nudges.'''

import json

from configsys import refreshstate, routes, versions
from configsys.app import main


class _Paths:
    def __init__(self, tmp):
        self.state_dir = tmp
        self.stale_pins_file = tmp / 'stale-pins.json'


def test_stale_pin_stamp_round_trip(tmp_path):
    p = _Paths(tmp_path)
    assert refreshstate.read_stale_pins(p) == {}                      # nothing stamped yet
    refreshstate.record_stale_pins(p, {'fossil': ['2.28', '2.29']})
    assert refreshstate.read_stale_pins(p) == {'fossil': ['2.28', '2.29']}
    refreshstate.record_stale_pins(p, {})                            # a fixed pin clears
    assert refreshstate.read_stale_pins(p) == {}


def test_latest_check_specs_resolve_upstream():
    # a url+regex page scrape (fossil) and a github tag-re (graalvm) each yield a version
    page = 'download fossil-linux-x64-2.29.tar.gz'
    assert versions.discover({'url': 'x', 'regex': 'x64-([0-9]+[.][0-9]+)[.]tar'}, None,
                             fetch=lambda u: page) == '2.29'
    gh = json.dumps({'tag_name': 'jdk-25.0.1', 'assets': []})
    assert versions.discover({'github': 'graalvm/graalvm-ce-builds', 'tag-re': 'jdk-([0-9][0-9.]*)'},
                             None, fetch=lambda u: gh) == '25.0.1'


def test_real_routes_wire_latest_check_onto_static_pins():
    _, comps, _, _ = routes.load('routes.hu', None, [], [])
    for comp in ('graalvm', 'fossil'):
        specs = [b.details.get('latest-check') for b in comps[comp].bindings
                 if b.details.get('latest-check')]
        assert specs and isinstance(specs[0], dict), f'{comp} should carry a latest-check spec'


def test_check_surfaces_a_stamped_stale_pin(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr('configsys.app.sys.version_info', (3, 12, 0))   # silence the python-floor warning
    state = tmp_path / '.config' / 'configsys'
    state.mkdir(parents=True)
    (state / 'stale-pins.json').write_text(json.dumps({'fossil': ['2.28', '2.29']}))
    rc = main(['--home', str(tmp_path), '--os', 'pop', '--pretend', 'check'])
    out = capsys.readouterr().out
    assert 'fossil' in out and '2.28' in out and '2.29' in out and 'bump it' in out
    assert rc == 0                                                   # advisory: a warning, not an error
