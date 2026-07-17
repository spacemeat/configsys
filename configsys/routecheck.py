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


class AmbiguityError(Exception):
    pass


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
    '''Validate every component. Raises AmbiguityError on the first offender.'''
    for name, component in components.items():
        check_component(name, component, cascade)
