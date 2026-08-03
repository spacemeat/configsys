#!/usr/bin/env python3
'''Run the version-floor sweep — check that every authored version FLOOR is (a) met by some install
method here and (b) honestly claimed by the method that declares it. See configsys/versionsweep.py.

Networked + slow (it queries each provider method's available version), so it's a maintenance / CI
tool, NOT part of pytest — like tools/namesweep.py. Exits nonzero if any floor is stranded or
dishonest. Reflects THIS machine's repos/discovery; run in per-distro containers for cross-distro
coverage.
'''
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from configsys import versionsweep                       # noqa: E402
from configsys.app import Context, build_parser          # noqa: E402


def main():
    ctx = Context(build_parser().parse_args(['check']))  # a ctx to load routes from; no args used
    if '--derive' in sys.argv:
        # auto-derive toolchain floors from each source recipe's manifest and print a ready-to-
        # commit `version-floors:` block (the maintainer's daily job). Needs the source plugin
        # loaded (its recipes carry the `via: source` repos), so run it with that config.
        from configsys import floorderive
        from configsys.versions import http_fetch
        floors = floorderive.derive_floors(ctx.routes.components, http_fetch)
        if not floors:
            print('# no source recipes with derivable (cargo/go) floors are loaded', file=sys.stderr)
        print(floorderive.emit_floors(floors), end='')
        return 0
    findings = versionsweep.sweep_ctx(ctx)
    for f in findings:
        print(versionsweep.format_finding(f))
    if findings:
        print(f'\nversion sweep: {len(findings)} floor issue(s) — fix the route or the floor.')
        return 1
    print('version sweep: OK — every declared version floor is met and honestly claimed.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
