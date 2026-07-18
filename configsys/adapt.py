'''adapt.py — build the app's ResolvedComponent objects from v2 resolution.

The v2 resolver produces Units (driver, component, package, details, deps,
requested_as). The rest of the app (planning, InstallState, the drivers, the TUI) is
driven by `{key: ResolvedComponent}`. This is the thin, permanent glue between them: it
carries no field translation — `unit.details` is already the install-field shape the
drivers read (normalized in resolve._install_fields). Not an adapter layer; just the
v2 resolver's output object mapped onto the driver contract.
'''

from .componentObj import ResolvedComponent


def to_resolved_component(unit):
    rc = ResolvedComponent(
        key=unit.key,
        driver=unit.driver,
        comp=unit.component,
        fields=dict(unit.details),
        vars={},                      # v2 carries version info in `version:` specs, not $VARS
        source=unit.source or '',     # the .hu file that defined the component (content roots)
    )
    rc.requested_as = set(unit.requested_as)
    rc.deps = set(unit.deps)
    return rc


def to_resolved_components(units):
    '''{key: Unit} -> {key: ResolvedComponent}, the dict the app pipeline consumes.'''
    return {key: to_resolved_component(u) for key, u in units.items()}
