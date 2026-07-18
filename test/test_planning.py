from configsys.componentObj import ResolvedComponent
from configsys.planning import dependency_order, expand_plan


def u(key, deps=()):
    fam, comp = key.split('\\')
    return ResolvedComponent(key=key, driver=fam, comp=comp,
                             fields={'name': comp}, deps=set(deps))


UNITS = {
    'apt\\flatpak': u('apt\\flatpak'),
    'apt\\curl': u('apt\\curl'),
    'flatpak\\firefox': u('flatpak\\firefox', deps={'apt\\flatpak'}),
    'flatpak\\chrome': u('flatpak\\chrome', deps={'apt\\flatpak'}),
    'tarball\\vulkan-sdk': u('tarball\\vulkan-sdk', deps={'apt\\curl'}),
}


def test_dependency_order_puts_deps_first():
    order = dependency_order(UNITS)
    assert order.index('apt\\flatpak') < order.index('flatpak\\firefox')
    assert order.index('apt\\curl') < order.index('tarball\\vulkan-sdk')


def test_expand_install_folds_in_missing_dep_ordered():
    plan = [('install', 'flatpak\\firefox', UNITS['flatpak\\firefox'])]
    out = expand_plan(plan, UNITS)  # no states -> dep considered missing
    keys = [k for _op, k, _rc in out]
    assert keys == ['apt\\flatpak', 'flatpak\\firefox']
    assert all(op == 'install' for op, _k, _rc in out)


def test_expand_skips_dep_already_present():
    class S:
        def __init__(self, present):
            self.present = present
    states = {'apt\\flatpak': S(True), 'flatpak\\firefox': S(False)}
    plan = [('install', 'flatpak\\firefox', UNITS['flatpak\\firefox'])]
    out = expand_plan(plan, UNITS, states)
    keys = [k for _op, k, _rc in out]
    assert keys == ['flatpak\\firefox']  # dep present -> not re-added


def test_two_apps_share_one_dep_install():
    plan = [
        ('install', 'flatpak\\firefox', UNITS['flatpak\\firefox']),
        ('install', 'flatpak\\chrome', UNITS['flatpak\\chrome']),
    ]
    out = expand_plan(plan, UNITS)
    keys = [k for _op, k, _rc in out]
    assert keys.count('apt\\flatpak') == 1
    assert keys.index('apt\\flatpak') == 0  # dep first


def test_remove_not_expanded_and_reverse_ordered():
    plan = [
        ('remove', 'flatpak\\firefox', UNITS['flatpak\\firefox']),
        ('remove', 'apt\\flatpak', UNITS['apt\\flatpak']),
    ]
    out = expand_plan(plan, UNITS)
    keys = [k for _op, k, _rc in out]
    # dependent removed before its dependency (reverse dep order)
    assert keys.index('flatpak\\firefox') < keys.index('apt\\flatpak')
    assert all(op == 'remove' for op, _k, _rc in out)


def test_installs_before_removes():
    plan = [
        ('remove', 'flatpak\\chrome', UNITS['flatpak\\chrome']),
        ('install', 'flatpak\\firefox', UNITS['flatpak\\firefox']),
    ]
    out = expand_plan(plan, UNITS)
    ops = [op for op, _k, _rc in out]
    assert ops.index('install') < ops.index('remove')
