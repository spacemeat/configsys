'''`disabled-drivers:` — a machine setting that turns a driver OFF: its bindings become
non-matching here (like a false `when:`), so a `suggests:` targeting a component that only
installs via it is silently skipped, while a hard require / explicit want on such a component
errors honestly. The lever behind "I manage my own dotfiles" (disabled-drivers: [ dotfiles ]).'''

from configsys import layers
from configsys.config import Config
from configsys.routes import Resolver

OS = 'os: { linux: {}  debian: { using: linux  native: apt } }'
COMPS = '''
    app:      { suggests: app-dotfiles  install: [ { via: native } ] }
    app-dotfiles: { install: [ { via: dotfiles  config: { src: app  dst: ~/.app } } ] }
    harddot:  { requires: app-dotfiles  install: [ { via: native } ] }
'''


def _res(tmp_path, disabled=None):
    p = tmp_path / 'routes.hu'
    p.write_text('{ ' + OS + '  components: { ' + COMPS + ' } }')
    return Resolver(str(p), 'debian', '12', disabled=disabled)


def test_disabled_driver_makes_a_soft_dep_skip_silently(tmp_path):
    # baseline: app pulls its dotfiles via suggests
    base = _res(tmp_path)
    u, e = base.resolve_resilient(['app'])
    assert any('app-dotfiles' in k for k in u) and not e

    # disabled: app installs, its suggested dotfiles is silently skipped (no error)
    off = _res(tmp_path, disabled={'dotfiles'})
    u, e = off.resolve_resilient(['app'])
    assert any(k.endswith('\\app') for k in u)              # app itself still resolves
    assert not any('app-dotfiles' in k for k in u)          # the suggest skipped
    assert not e                                            # silently — never an error


def test_disabled_driver_hard_require_and_explicit_want_error(tmp_path):
    off = _res(tmp_path, disabled={'dotfiles'})
    # a HARD requires: on a now-unroutable component is an honest error
    _u, e = off.resolve_resilient(['harddot'])
    assert 'harddot' in e
    # an explicit want of the disabled-only component errors too
    _u, e = off.resolve_resilient(['app-dotfiles'])
    assert 'app-dotfiles' in e
    # and it's hidden from the candidate/method listing
    assert off.candidates('app-dotfiles') == []


def test_config_reads_disabled_drivers_machine_setting():
    c = Config([
        layers.Layer('config.hu', 'repo', layers.materialize_string('{ }')),
        layers.Layer('user.hu', 'user',
                     layers.materialize_string('{ disabled-drivers: [ dotfiles, snap ] }')),
    ])
    assert set(c.disabled_drivers()) == {'dotfiles', 'snap'}
    # unset -> empty
    c2 = Config([layers.Layer('config.hu', 'repo', layers.materialize_string('{ }'))])
    assert list(c2.disabled_drivers()) == []
