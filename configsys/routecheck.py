'''check.py — the static ambiguity check.

The soundness promise of the `when:` model: for any two candidates (a component's
bindings, or a capability's providers) whose match-sets OVERLAP, one must be a subset
of the other. If every overlapping pair is comparable, resolution is provably
unambiguous for every possible machine. Any overlapping-but-incomparable pair is a
load-time error, pointing at a witness context — never a silent tiebreak.

Run check_all() when loading routes.hu to reject an ambiguous routes file up front.
'''

from itertools import combinations

from . import predicate
from .errors import ConfigsysError


class AmbiguityError(ConfigsysError):
    '''Two overlapping-but-incomparable candidates — a load-time config error.'''


def check_component(name, component, cascade):
    '''Verify a component's bindings are pairwise-comparable-where-overlapping.'''
    preds = [b.pred for b in component.bindings]
    for (i, a), (j, b) in combinations(enumerate(preds), 2):
        if predicate.overlap(a, b, cascade) and not predicate.comparable(a, b, cascade):
            raise AmbiguityError(
                f'component {name!r}: bindings #{i} and #{j} overlap but neither is more '
                f'specific (e.g. on {predicate.witness(a, b, cascade)}) — make them '
                f'comparable (one a subset of the other) or disjoint')


def check_all(components, cascade):
    '''Validate every component. Raises AmbiguityError on the first offender. This is the
    fast load-time gate (ambiguity only — see validate() for the full lint).'''
    for name, component in components.items():
        check_component(name, component, cascade)


# -- full lint (for `configsys check`) ------------------------------------

class Issue:
    '''One problem found by validate(). `severity` is 'error' (definitely broken) or
    'warning' (localized — breaks only that component when used).'''

    def __init__(self, kind, message, component=None, source=None, severity='error'):
        self.kind = kind
        self.message = message
        self.component = component       # component name, or None (e.g. a mechanism issue)
        self.source = source             # the file it came from (provenance)
        self.severity = severity

    @property
    def is_error(self):
        return self.severity == 'error'


_SPECIAL_VIA = frozenset({'native', 'parts'})   # resolver mechanisms that aren't Families


def _as_list(v):
    return [] if v is None else (v if isinstance(v, list) else [v])


def _providable_caps(components, cascade):
    '''Every capability something could provide: each LIVE component's name + its provides
    (a removed `{}` component provides nothing), plus environment caps from the OS blocks.'''
    caps = set()
    for name, comp in components.items():
        if comp.bindings or comp.provides:
            caps.add(name)
            caps.update(comp.provides)
    for block in cascade.blocks:
        caps.update(cascade.provides(block))
    return caps


def validate(components, cascade, mechanisms):
    '''Lint the merged component set -> [Issue] (empty = clean). Covers ambiguity, unknown
    via: mechanism, unknown component in parts: (all errors), and when:-names-unknown-OS +
    requires-nothing-provides (warnings — localized). Attribution via each Component.source.'''
    from .drivers import supported_names
    valid_via = _SPECIAL_VIA | supported_names()
    providable = _providable_caps(components, cascade)
    issues = []

    def add(kind, msg, comp, sev='error'):
        issues.append(Issue(kind, msg, comp.name, comp.source, sev))

    for name, comp in components.items():
        try:
            check_component(name, comp, cascade)
        except AmbiguityError as e:
            add('ambiguity', str(e), comp)
        for b in comp.bindings:
            if b.via not in valid_via:
                add('unknown-via', f'via:{b.via!r} is not a known mechanism/family', comp)
            for os_name in predicate.os_names(b.pred):
                if os_name not in cascade.blocks:
                    add('unknown-os', f'when: names unknown OS {os_name!r}', comp, 'warning')
            if b.via == 'parts':
                for part in _as_list(b.details.get('parts')):
                    if part not in components:
                        add('unknown-part', f'parts references unknown component {part!r}', comp)
            for cap in _as_list(b.details.get('requires')):
                if cap not in providable:
                    add('dangling-requires', f'requires {cap!r} which nothing provides', comp, 'warning')
        for cap in comp.requires:
            if cap not in providable:
                add('dangling-requires', f'requires {cap!r} which nothing provides', comp, 'warning')

    for mech, reqs in mechanisms.items():
        for cap in reqs:
            if cap not in providable:
                issues.append(Issue('dangling-requires',
                    f'mechanism {mech!r} requires {cap!r} which nothing provides',
                    None, None, 'warning'))
    return issues
