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


# --- C++ standard library, decoupled from the compiler ---

def test_clang_pulls_gcc_toolchain_and_libstdcxx_via_gxx_on_debian():
    # clang ships no stdlib and no C runtime on Linux: it pulls the gcc toolchain (crt/libgcc) + a
    # C++ stdlib via cxx-stdlib, but never the cpp-toolchain (cxx) COMPONENT. On Debian the default
    # libstdc++ dev headers are only installable via g++ (libstdc++-dev is a virtual package), so
    # cxx-stdlib resolves to the g++ package there.
    u = Resolver(ROUTES, 'ubuntu', '24.04').resolve_names(['clang-19'])
    assert u['apt\\c-toolchain'].name == 'gcc'
    assert u['apt\\libstdc++'].name == 'g++'      # Debian: g++ pulls the default libstdc++-N-dev
    assert 'apt\\cpp-toolchain' not in u          # clang requires cxx-stdlib, not the cxx compiler


def test_clang_requires_the_toolchain_component_not_the_cc_capability():
    # clang provides cc (opt-in); if it required the `cc` capability it would self-satisfy and never
    # pull gcc. It requires the c-toolchain COMPONENT instead, so gcc is always present.
    r = Resolver(ROUTES, 'ubuntu', '24.04')
    assert 'c-toolchain' in r.components['clang-19'].requires
    assert 'cxx-stdlib' in r.components['clang-19'].requires


def test_libcxx_is_optin_and_pinnable_for_clang():
    # cxx-stdlib defaults to libstdc++ (unambiguous despite libc++ also providing it, since libc++ is
    # opt-in); provider-pinning cxx-stdlib -> libc++ swaps the stdlib with no g++/libstdc++.
    r = Resolver(ROUTES, 'ubuntu', '24.04')
    assert r.components['libc++'].opt_in and not r.components['libstdc++'].opt_in
    assert Resolver(ROUTES, 'ubuntu', '24.04').resolve_names(['libstdc++'])['apt\\libstdc++'].name == 'g++'
    pinned = Resolver(ROUTES, 'ubuntu', '24.04', pins={'cxx-stdlib': 'libc++'}).resolve_names(['clang-19'])
    assert pinned['apt\\libc++'].name == 'libc++-dev'
    assert 'apt\\libstdc++' not in pinned


def test_libcxx_abi_split_except_on_alpine():
    # libc++ soft-suggests libc++abi (a separate dev package on apt/dnf; bundled into libc++ on Alpine)
    assert 'apt\\libc++abi' in Resolver(ROUTES, 'ubuntu', '24.04').resolve_names(['libc++'])
    assert 'apk\\libc++abi' not in Resolver(ROUTES, 'alpine', '3.20').resolve_names(['libc++'])
