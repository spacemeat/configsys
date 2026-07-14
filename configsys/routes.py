'''routes.py — RouteResolver: turn OS-level component names into concrete units.

Owns every bit of routes.hu semantics:
  * OS cascade via `!using` (pop_os! -> ubuntu -> debian -> linux)
  * `family\\comp` binding, and the `*` wildcard (`*: apt\\*`)
  * list routes = multi-part components (each entry resolved independently)
  * dict routes with `package: family\\comp` = indirect binding
  * `$VAR` substitution from family-level and component-level variables (fonts)
  * recursive dependency resolution with cycle guarding and unit-level dedup
'''

import re

import humon as h

from .componentObj import ResolvedComponent
from .errors import ConfigError, ResolveError

_VAR_RE = re.compile(r'\$[A-Za-z_][A-Za-z0-9_]*')

DICT = h.NodeKind.DICT
LIST = h.NodeKind.LIST
VALUE = h.NodeKind.VALUE


class RouteResolver:
    def __init__(self, trove, os_block):
        self.trove = trove          # keep alive: Nodes point into it
        self.root = trove.root
        self.os_block = os_block
        self.cascade = self._build_cascade(os_block)

    # -- cascade ----------------------------------------------------------

    def _build_cascade(self, start):
        chain = []
        seen = set()
        name = start
        while name and name not in seen:
            blk = self.root[name]
            if blk is None:
                if name == start:
                    raise ConfigError(f'unknown OS block: "{name}"')
                break  # dangling !using target — end of chain
            seen.add(name)
            chain.append((name, blk))
            using = blk['!using']
            name = using.value if using is not None else None
        return chain

    @property
    def cascade_names(self):
        return [n for n, _ in self.cascade]

    # -- public API -------------------------------------------------------

    def resolve_names(self, names):
        '''Resolve an iterable of OS-level names -> {unit_key: ResolvedComponent}.'''
        return self.resolve_with_roots(names)[0]

    def resolve_with_roots(self, names):
        '''Like resolve_names, but also return the set of unit keys bound *directly*
        by the named components (excluding auto-added family deps).'''
        units, roots = {}, set()
        for n in names:
            roots |= self._resolve_one(n, n, units, frozenset())
        return units, roots

    # -- lookup -----------------------------------------------------------

    def _lookup(self, name):
        for bname, blk in self.cascade:          # exact name wins, most-derived first
            node = blk[name]
            if node is not None:
                return node, bname, False
        for bname, blk in self.cascade:          # else nearest wildcard
            star = blk['*']
            if star is not None:
                return star, bname, True
        return None, None, False

    def _resolve_one(self, name, root, units, visiting):
        '''Resolve one OS-level name; returns the set of unit keys it bound.'''
        if name in visiting:
            return set()  # cycle guard
        visiting = visiting | {name}
        node, _bname, _is_star = self._lookup(name)
        if node is None:
            raise ResolveError(name, self.os_block,
                               'not found in OS cascade and no * wildcard')
        return self._interpret(node, name, root, units, visiting)

    def _interpret(self, node, name, root, units, visiting):
        kind = node.kind
        keys = set()
        if kind == LIST:
            for i in range(node.num_children):
                keys |= self._interpret_value(node[i], name, root, units, visiting)
        elif kind == DICT:
            pkg = node['package']
            if pkg is None:
                raise ResolveError(name, self.os_block,
                                   'dict route without a `package` reference')
            keys |= self._bind_ref(pkg.value, name, root, units, visiting, extra=node)
        else:  # VALUE
            keys |= self._interpret_value(node, name, root, units, visiting)
        return keys

    def _interpret_value(self, node, name, root, units, visiting):
        val = node.value
        if val is None:
            # nested container as a list entry (not used by current data, but safe)
            return self._interpret(node, name, root, units, visiting)
        if '\\' in val:
            return self._bind_ref(val, name, root, units, visiting)
        return self._resolve_one(val, root, units, visiting)  # bare name reference

    # -- binding ----------------------------------------------------------

    def _bind_ref(self, ref, requested_name, root, units, visiting, extra=None):
        family, _, comp = ref.partition('\\')
        if comp == '*':
            comp = requested_name

        fam_block = self.root['\\' + family]
        if fam_block is None:
            raise ResolveError(requested_name, self.os_block,
                               f'unknown family "{family}"')
        comp_node = fam_block[comp]
        if comp_node is None:
            raise ResolveError(requested_name, self.os_block,
                               f'"{comp}" not defined in family "{family}"')

        fam_vars = self._block_vars(fam_block)
        comp_vars, fields = self._split_vars_fields(comp_node)
        varmap = self._resolve_vars({**fam_vars, **comp_vars})

        fields = {k: (self._subst(v, varmap) if isinstance(v, str) else v)
                  for k, v in fields.items()}
        if extra is not None:                    # merge OS-dict extras (minus `package`)
            _, extra_fields = self._split_vars_fields(extra)
            extra_fields.pop('package', None)
            fields.update({k: (self._subst(v, varmap) if isinstance(v, str) else v)
                           for k, v in extra_fields.items()})

        key = f'{family}\\{comp}'
        rc = units.get(key)
        if rc is None:
            rc = ResolvedComponent(key=key, family=family, comp=comp,
                                   fields=fields, vars=varmap,
                                   source=comp_node.address)
            units[key] = rc
            # family-level !depends: auto-add the tool(s) this family needs, first.
            for dep_name in self._family_depends(fam_block):
                if dep_name != requested_name:   # a family never depends on its own bind name
                    rc.deps |= self._resolve_one(dep_name, root, units, visiting)
        rc.requested_as.add(root)
        return {key}

    @staticmethod
    def _family_depends(fam_block):
        node = fam_block['!depends']
        if node is None:
            return []
        if node.kind == LIST:
            return [node[i].value for i in range(node.num_children)]
        return [node.value]

    # -- variables & fields ----------------------------------------------

    @staticmethod
    def _block_vars(block):
        out = {}
        for i in range(block.num_children):
            ch = block[i]
            if ch.key and ch.key.startswith('$'):
                out[ch.key] = ch.value
        return out

    @classmethod
    def _split_vars_fields(cls, node):
        variables, fields = {}, {}
        for i in range(node.num_children):
            ch = node[i]
            k = ch.key
            if not k:
                continue
            if k.startswith('$'):
                variables[k] = ch.value
            else:
                fields[k] = cls._node_to_py(ch)   # scalar, list, or nested dict
        return variables, fields

    @classmethod
    def _node_to_py(cls, node):
        '''Convert a humon node to plain python (str / list / nested dict). Lets
        families carry structured fields, e.g. dotfiles link specs.'''
        if node.kind == DICT:
            out = {}
            for i in range(node.num_children):
                ch = node[i]
                if ch.key:
                    out[ch.key] = cls._node_to_py(ch)
            return out
        if node.kind == LIST:
            return [cls._node_to_py(node[i]) for i in range(node.num_children)]
        return node.value

    def _resolve_vars(self, varmap):
        out = dict(varmap)
        for _ in range(10):
            changed = False
            for k, v in list(out.items()):
                if isinstance(v, str):
                    nv = self._subst(v, out)
                    if nv != v:
                        out[k], changed = nv, True
            if not changed:
                break
        return out

    @staticmethod
    def _subst(s, varmap):
        return _VAR_RE.sub(lambda m: varmap.get(m.group(0), m.group(0)), s)
