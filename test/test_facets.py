'''Facets — detected environment atoms in `when:`. Categorical (`gpu:nvidia`, like `cpu:`) and
versioned (`cuda >= 12`, like a versioned OS atom but keyed by a facet name). Covers parse, eval
(present / absent / list / version compare), and specificity over the grid (a facet-gated
predicate is strictly narrower than a broad one; disjoint facet values don't overlap).'''

import os

import pytest

from configsys import routes
from configsys.predicate import (ALWAYS, Categorical, Context, Os, comparable, overlap, parse,
                                 subset)

SR = {'ubuntu', 'debian', 'fedora'}


def ctx(*, gpu=(), cuda=None):
    return Context(['ubuntu', 'debian', 'linux'], '24.04', 'x86_64', SR,
                   facets_cat={'gpu': gpu} if gpu else None,
                   facets_ver={'cuda': cuda} if cuda is not None else None)


def _cascade():
    return routes.load(os.path.join(os.path.dirname(__file__), '..', 'routes.hu'))[0]


# -- parse -----------------------------------------------------------------

def test_parse_categorical_and_versioned_facets():
    assert isinstance(parse('gpu: nvidia'), Categorical)
    assert parse('gpu: nvidia').ns == 'gpu' and parse('gpu: nvidia').values == frozenset(['nvidia'])
    # a versioned facet parses as the same node shape as a versioned OS atom (resolved at eval time)
    n = parse('cuda >= 12')
    assert isinstance(n, Os) and n.name == 'cuda' and n.op == '>=' and n.version == (12,)


# -- eval: categorical -----------------------------------------------------

def test_categorical_facet_present_absent_and_list():
    assert parse('gpu: nvidia').eval(ctx(gpu=['nvidia']))
    assert not parse('gpu: nvidia').eval(ctx())                    # facet absent -> false
    assert not parse('gpu: nvidia').eval(ctx(gpu=['amd']))         # wrong tag
    assert parse('gpu: [ nvidia, amd ]').eval(ctx(gpu=['amd']))    # any-of
    assert parse('gpu: nvidia').eval(ctx(gpu=['nvidia', 'amd']))   # multi-GPU machine


# -- eval: version ---------------------------------------------------------

def test_version_facet_compare():
    assert parse('cuda >= 12').eval(ctx(cuda='12.4'))
    assert parse('cuda >= 12').eval(ctx(cuda='12.0'))
    assert not parse('cuda >= 12').eval(ctx(cuda='11.5'))
    assert parse('cuda < 12').eval(ctx(cuda='11.5'))
    assert not parse('cuda >= 12').eval(ctx())                     # absent -> false, never mis-fires


def test_version_facet_does_not_collide_with_os_version():
    # `cuda` isn't an OS block, so its version is the facet's, independent of the OS version (24.04)
    assert parse('ubuntu and cuda >= 12').eval(ctx(cuda='12.4'))
    assert not parse('ubuntu and cuda >= 12').eval(ctx(cuda='11.5'))


# -- specificity / grid ----------------------------------------------------

def test_facet_gated_is_strictly_more_specific():
    c = _cascade()
    narrow, broad = parse('gpu: nvidia'), ALWAYS
    assert subset(narrow, broad, c)               # every nvidia machine is matched by the broad one
    assert not subset(broad, narrow, c)           # ...but not vice-versa -> strictly narrower
    # same for a version facet
    assert subset(parse('cuda >= 12'), ALWAYS, c)
    assert not subset(ALWAYS, parse('cuda >= 12'), c)


def test_disjoint_facet_values_do_not_overlap():
    c = _cascade()
    assert not overlap(parse('gpu: nvidia'), parse('gpu: amd'), c)   # no single-GPU cell is both
    assert not comparable(parse('gpu: nvidia'), parse('cuda >= 12'), c)  # different facets, incomparable


def test_version_facet_specificity_nests():
    c = _cascade()
    assert subset(parse('cuda >= 12'), parse('cuda >= 11'), c)       # >=12 ⊆ >=11
    assert not subset(parse('cuda >= 11'), parse('cuda >= 12'), c)


# -- end-to-end: a facet gates which binding resolves -----------------------

_ROUTES = ('{ os: { linux: {}  debian: { using: linux  native: apt } }'
           '  facets: { gpu: { kind: categorical  detect: "true"'
           '                   match: { nvidia: "NVIDIA"  amd: "AMD" } } }'
           '  components: { thing: { install: ['
           '    { via: native }'
           '    { via: script  when: "gpu:nvidia"  install-cmd: "x"  version-cmd: "x"'
           '      version-re: "(.*)"  uninstall-cmd: "x" } ] } } }')


def test_facet_gated_binding_selection(tmp_path, monkeypatch):
    from configsys.routes import Resolver
    p = tmp_path / 'routes.hu'
    p.write_text(_ROUTES)
    monkeypatch.delenv('CONFIGSYS_FACET_gpu', raising=False)          # no GPU (detect `true` -> no match)
    assert set(Resolver(str(p), 'debian', '12').resolve_names(['thing'])) == {'apt\\thing'}
    monkeypatch.setenv('CONFIGSYS_FACET_gpu', 'nvidia')              # inject an NVIDIA GPU
    assert set(Resolver(str(p), 'debian', '12').resolve_names(['thing'])) == {'script\\thing'}
