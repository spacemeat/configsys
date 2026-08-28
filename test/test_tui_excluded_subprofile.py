'''Regression: an explicitly-excluded subprofile (`~name` where name is a nested subprofile) must
not appear in the Components tree at all — it was leaking in as an empty 'unsupported' node. The
distinction that must survive: an EXCLUDED subprofile contributes no units (empty -> pruned), while
an OS-UNSUPPORTED subprofile's units ARE present (just unsupported) and stays visible.'''

from types import SimpleNamespace

from configsys.installState import ComponentState
from configsys.tui import menu


def _cs(key, name, supported=True):
    comp = SimpleNamespace(key=key, comp=name, name=name, driver='native', requested_as=[name])
    return ComponentState(component=comp, supported=supported, present=False,
                          installed_version=None, latest_version=None, locked=False,
                          lock_source=None, managed=False, error=None)


# meta includes two subprofiles (kept, gone); `top` is the active profile. `gone` is excluded, so its
# unit never enters the resolved `states` — exactly what a nested `~gone` produces.
_LAYOUTS = [('top',  [('include', 'meta')]),
            ('meta', [('include', 'kept'), ('include', 'gone')]),
            ('kept', [('component', 'kc')]),
            ('gone', [('component', 'gc')])]
_TRANSITIVE = {'top': ['kc'], 'meta': ['kc', 'gc'], 'kept': ['kc'], 'gone': ['gc']}


def _labels(states):
    ms = menu.MenuState(states, _LAYOUTS, _TRANSITIVE)
    return [n.label for n in ms._all_nodes()]


def test_excluded_subprofile_pruned_from_tree():
    labels = _labels({'native\\kc': _cs('native\\kc', 'kc')})    # only the KEPT unit resolves
    assert 'gone' not in labels                                  # excluded -> no link, no top node
    assert 'kept' in labels                                      # a kept sibling still shows
    assert 'meta' in labels and 'top' in labels


def test_present_but_unsupported_subprofile_still_shows():
    # `gc` IS resolved but unsupported on this OS -> NOT an exclusion, must remain visible.
    labels = _labels({'native\\kc': _cs('native\\kc', 'kc'),
                      'native\\gc': _cs('native\\gc', 'gc', supported=False)})
    assert 'gone' in labels
