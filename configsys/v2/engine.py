'''engine.py — the app-facing v2 resolver.

Presents the same surface the app already calls on RouteResolver (`resolve_names`,
`resolve_with_roots`), but backed by the v2 capability/component model: load routes2.hu
once, then resolve a profile to `{key: ResolvedComponent}` for this machine's context
(OS block + version + cpu). This is the object `Context.routes` returns when the v2
resolver is selected; everything downstream (planning, InstallState, families, TUI) is
unchanged because the dict shape is identical.
'''

from . import routes2
from .adapt import to_resolved_components
from .resolve import resolve_roots


class V2Resolver:
    def __init__(self, routes_path, block, version=None, cpu=None, pins=None):
        self.cascade, self.components, self.mechanisms = routes2.load(routes_path)
        self.block = block
        self.version = version
        self.cpu = cpu
        self.pins = pins or {}

    def _resolve(self, names):
        return resolve_roots(list(names), self.cascade, self.components, self.mechanisms,
                             self.block, self.version, self.cpu, self.pins)

    def resolve_names(self, names):
        units, _roots = self._resolve(names)
        return to_resolved_components(units)

    def resolve_with_roots(self, names):
        units, roots = self._resolve(names)
        return to_resolved_components(units), roots
