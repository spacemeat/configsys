'''Python interpreters as version-scoped providers of `python3` (routes.hu data): each version
coexists, a versioned floor selects the right one, and the SYSTEM python covers a bare requirement
for free (the OS `provides: python3`). Uses the real base routes on a debian context.'''

from configsys.app import Context, build_parser
from configsys.routes import Component


def _routes():
    return Context(build_parser().parse_args(['--os', 'pop', 'inspect'])).routes


def _units(r, names):
    res = r.resolve_resilient(names)
    return res[0] if isinstance(res, tuple) else res


def test_interpreters_offer_native_and_pyenv():
    r = _routes()
    for n in ('python3.11', 'python3.12', 'python3.13'):
        vias = [c['via'] for c in r.candidates(n)]
        assert 'native' in vias and 'pyenv' in vias, (n, vias)


def test_bare_python3_is_satisfied_by_the_system_for_free():
    # cython requires bare `python3` -> met by the OS `provides: python3`; NO interpreter installed.
    d = _units(_routes(), ['cython'])
    assert not any('python3.' in k for k in d)              # no python3.X unit pulled
    assert any(k.endswith('\\cython') for k in d)


def test_versioned_floor_selects_the_interpreter():
    r = _routes()
    r.components['need311'] = Component('need311', {'requires': {'python3': '>=3.11'},
                                                    'install': [{'via': 'native'}]})
    r.components['needold'] = Component('needold', {'requires': {'python3': '<3.12'},
                                                    'install': [{'via': 'native'}]})
    assert 'apt\\python3.13' in _units(r, ['need311'])      # 3.13 is the default among qualifiers
    assert 'apt\\python3.11' in _units(r, ['needold'])      # `<3.12` enables the never-auto -11


def test_two_interpreters_coexist():
    r = _routes()
    r.components['newer'] = Component('newer', {'requires': {'python3': '>=3.13'},
                                                'install': [{'via': 'native'}]})
    r.components['older'] = Component('older', {'requires': {'python3': '<3.12'},
                                               'install': [{'via': 'native'}]})
    d = _units(r, ['newer', 'older'])
    assert 'apt\\python3.13' in d and 'apt\\python3.11' in d   # both resident, side by side
