'''The versioned gcc/clang toolchains carry language-standard capabilities (real routes.hu data).

Each `gcc-NN` / `clang-NN` `provides:` the standards its compiler accepts (`cc`/`cxx` + C11/
C17/C23 and "C++17"/"C++20"/...) so a build can `requires: "C++20"` (or pin `gcc-15`). They are
`opt-in: true`, so a plain `requires: cxx` still resolves to the unversioned `cpp-toolchain`
(the system default) with no ambiguity — the opt-in mechanics themselves live in
test_optin_provider.py; this pins the actual toolchain data.'''

import os

from configsys.routes import Resolver

ROUTES = os.path.join(os.path.dirname(__file__), '..', 'routes.hu')

VERSIONED = ['gcc-13', 'gcc-14', 'gcc-15', 'clang-18', 'clang-19', 'clang-20']


def test_versioned_compilers_provide_standards_and_are_optin():
    r = Resolver(ROUTES, 'ubuntu', '24.04')
    for name in VERSIONED:
        comp = r.components[name]
        assert comp.opt_in, f'{name} must be opt-in so it does not shadow cpp-toolchain'
        for cap in ('cc', 'cxx', 'C11', 'C17', 'C23', 'C++17', 'C++20', 'C++23'):
            assert cap in comp.provides, f'{name} should provide {cap}'
    # the newest gain C++26, the older ones do not (a hand-tunable label)
    assert 'C++26' in r.components['gcc-15'].provides
    assert 'C++26' in r.components['clang-20'].provides
    assert 'C++26' not in r.components['gcc-13'].provides


def test_plain_cxx_stays_unambiguous():
    # despite six versioned providers of cxx, a plain requirement resolves to the default toolchain
    u = Resolver(ROUTES, 'ubuntu', '24.04').resolve_names(['cpp-toolchain'])
    assert u['apt\\cpp-toolchain'].name == 'g++'


def test_versioned_gcc_self_satisfies_cxx():
    # gcc-15 IS a C++ compiler (provides cxx), so its own `requires: cxx` self-satisfies once it is
    # wanted — it must NOT redundantly pull the base cpp-toolchain/c-toolchain.
    u = Resolver(ROUTES, 'ubuntu', '24.04').resolve_names(['gcc-15'])
    assert 'gcc\\gcc-15' in u
    assert not any('cpp-toolchain' in k or 'c-toolchain' in k for k in u)
