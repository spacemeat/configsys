'''floorderive — auto-derive version FLOORS from each source recipe's build manifest.

A `via: source` binding that `requires: cargo` builds a Rust project whose Cargo.toml declares an
MSRV (`rust-version`); one that `requires: go` builds a Go project whose go.mod declares a minimum
(`go 1.25`). This reads those manifests straight from each recipe's repo and emits the floor —
`{ component: { cap: ">=X" } }` — the shape the `version-floors:` section consumes. The maintainer's
daily sweep runs this and commits/publishes the result (e.g. to a `main`-keyed version-data plugin),
so recipe authors never hand-maintain toolchain floors.

Pure given an injected `fetch(url) -> text` (unit-tested offline); the CLI wires it to http_fetch.
'''

import re

from .resolve import cap_names

# cap -> (manifest path in the repo, extractor of the minimum version from its text)
_RUST_VER = re.compile(r'^\s*rust-version\s*=\s*["\']([0-9]+(?:\.[0-9]+){0,2})["\']', re.M)
_GO_VER = re.compile(r'^\s*go\s+([0-9]+\.[0-9]+(?:\.[0-9]+)?)\s*$', re.M)


def _rust_msrv(text):
    m = _RUST_VER.search(text or '')
    return m.group(1) if m else None


def _go_directive(text):
    m = _GO_VER.search(text or '')
    return m.group(1) if m else None


DERIVERS = {
    'cargo': ('Cargo.toml', _rust_msrv),
    'go': ('go.mod', _go_directive),
}


def _raw_url(repo, path, ref='HEAD'):
    '''A github repo URL + in-repo path -> the raw.githubusercontent URL for `ref`.'''
    r = repo.rstrip('/')
    if r.endswith('.git'):
        r = r[:-4]
    for pre in ('https://github.com/', 'http://github.com/', 'github.com/'):
        if r.startswith(pre):
            r = r[len(pre):]
            break
    return f'https://raw.githubusercontent.com/{r}/{ref}/{path}'


def built_ref(binding, paths=None):
    '''The git ref a `via: source` binding actually CHECKS OUT — its explicit `ref:`, else the
    resolved release tag (`tag-prefix` + discovered `version:`), else HEAD. Mirrors source._ref, so
    a floor is derived from the version the binding BUILDS — not HEAD, which can carry an unreleased
    MSRV bump higher than the tag you'd compile.'''
    d = binding.details
    if d.get('ref'):
        return str(d['ref'])
    spec = d.get('version')
    if isinstance(spec, dict):
        from .versions import discover
        v = discover(spec, paths)
        if v:
            return f"{d.get('tag-prefix', '')}{v}"
    return 'HEAD'


def derive_floors(components, fetch, ref_of=built_ref):
    '''{ component: { cap: ">=X" } } auto-derived from each `via: source` recipe's manifest, read at
    the ref that binding BUILDS (`ref_of(binding) -> git-ref`; default built_ref). `fetch(url) ->
    text` (a fetch failure just skips that manifest). Only caps the recipe actually requires and
    that we know how to derive (cargo/go) are emitted, so the result maps 1:1 onto a
    `version-floors:` section that tightens real requirements.'''
    floors = {}
    for name, comp in components.items():
        for b in comp.bindings:
            if b.via != 'source' or not b.details.get('repo'):
                continue
            repo = b.details['repo']
            ref = ref_of(b) or 'HEAD'
            for cap in cap_names(b.details.get('requires')):
                spec = DERIVERS.get(cap)
                if not spec:
                    continue
                path, extract = spec
                try:
                    text = fetch(_raw_url(repo, path, ref))
                except Exception:  # noqa: BLE001 — a fetch failure is just "no floor derived"
                    text = None
                ver = extract(text) if text else None
                if ver:
                    floors.setdefault(name, {})[cap] = f'>={ver}'
    return floors


def emit_floors(floors):
    '''Render derived floors as a ready-to-commit `version-floors:` block.'''
    from .troveio import emit_hu
    return emit_hu({'version-floors': {k: floors[k] for k in sorted(floors)}})
