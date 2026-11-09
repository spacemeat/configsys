'''trustgate.py — which bindings an UNTRUSTED plugin layer may contribute (docs/plugins.md §6).

"Data, not script" is not a security boundary (docs/principles.md): a binding that adds an apt
repository or key, installs an upstream `.deb`, downloads a tarball or AppImage, builds a crate,
links a template into `~/.zshenv` or adds you to a group is as powerful as a shell recipe. So a
plugin layer that isn't trusted (`configsys plugin trust`, `plugins.command_source_trusted`) may
still DEFINE components, profiles, os blocks and drivers — but the only bindings of its that are
candidates are packages BY NAME from a registry this system already trusts: the distro's own
repos, Flathub, the Snap Store, Homebrew core (a driver class with `trusted_registry = True`),
setting none of that driver's `command_fields` (a repo / key / remote / debconf answer / classic
confinement — anything that runs a command or widens privilege) and no `version: { url: }` (a
fetch at inspect time). Everything else waits for trust, as an "untrusted" reason in `where` /
the resolve error instead of a candidate (review-2026-11-2 A1).

The gate sits at resolution (resolve._matching), so every surface agrees; run_plan checks it
again before running a step (defense in depth, e.g. for an install receipt replayed later).
'''

import os


def binding_needs_trust(via, details, native_driver=None):
    '''Why a binding with this `via:` and these fields carries commands / privileged writes /
    downloads (so an untrusted layer may not contribute it), or None when it's a plain package by
    name from a trusted registry. `native_driver` = the manager `via: native` resolves to here.'''
    from .drivers import _REGISTRY
    details = details or {}
    if via == 'parts':                               # a pure aggregator: no unit of its own
        return None
    ver = details.get('version')
    if isinstance(ver, dict) and ver.get('url'):
        return 'it fetches a version from a URL'
    name = native_driver if via == 'native' else via
    cls = _REGISTRY.get(name)
    if cls is None:
        return f'via: {via} is a driver configsys only runs from trusted layers'
    if not getattr(cls, 'trusted_registry', False):
        return f'via: {via} runs, builds or downloads code'
    fields = sorted(set(details) & set(getattr(cls, 'command_fields', ())))
    if fields:
        return f'its {", ".join(fields)} field(s) change system configuration as root'
    return None


def gated(binding, context):
    '''The reason `binding` is not a candidate because its layer is an untrusted plugin, or None.
    `context.untrusted_sources` = the normalized paths of untrusted plugin layer files (set by
    routes.load from its `command_trust`); a hand-built context has none.'''
    srcs = getattr(context, 'untrusted_sources', None)
    src = getattr(binding, 'source', None)
    if not srcs or not src or os.path.normpath(src) not in srcs:
        return None
    return binding_needs_trust(binding.via, binding.details, getattr(context, 'native_driver', None))


def unit_needs_trust(rc, native_driver=None):
    '''`binding_needs_trust` for a resolved unit (its via + fields) — for run_plan's re-check.'''
    return binding_needs_trust(getattr(rc, 'via', None) or rc.driver, getattr(rc, 'fields', {}),
                               rc.driver if (getattr(rc, 'via', None) == 'native') else native_driver)
