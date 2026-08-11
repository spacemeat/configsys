'''predicate.py — the `when:` boolean DSL: parse, evaluate, and rank by specificity.

Grammar (recursive descent):
    expr     := or_expr
    or_expr  := and_expr ('or' and_expr)*
    and_expr := not_expr ('and' not_expr)*
    not_expr := 'not' not_expr | atom
    atom     := '(' expr ')' | cpu_atom | os_atom
    cpu_atom := 'cpu' ':' (IDENT | '[' IDENT (','? IDENT)* ']')
    os_atom  := IDENT [ CMP VERSION ]          # bare OS (subtree) or versioned (scale-bound)

Semantics against a Context ⟨lineage, version, cpu, scale-roots⟩:
  * bare OS atom      -> the block is in the system's lineage (subtree membership)
  * versioned OS atom -> in lineage AND the atom's scale-root == the system's scale-root
                         (so `debian < 12` never matches Pop, which is on ubuntu's scale)
  * cpu atom          -> the system cpu is in the set

Evaluation is general over `and`/`or`/`not`. Specificity is set-inclusion over a per-dimension
"box"; the grid-based ambiguity checker handles the full boolean case (`or`/`not` included), so
negation is not restricted to OS atoms.
'''

import itertools
import operator
import re

from .errors import ConfigsysError
from .osversion import parse_version

_CMP = {'<': operator.lt, '<=': operator.le, '>': operator.gt,
        '>=': operator.ge, '=': operator.eq, '==': operator.eq}

_TOKEN = re.compile(r'''
      (?P<ws>\s+)
    | (?P<cmp><=|>=|==|<|>|=)
    | (?P<lparen>\()   | (?P<rparen>\))
    | (?P<lbrack>\[)   | (?P<rbrack>\])
    | (?P<comma>,)     | (?P<colon>:)
    | (?P<version>\d+(?:\.\d+)*)
    | (?P<ident>[A-Za-z_][A-Za-z0-9_]*!?)
''', re.VERBOSE)

_KEYWORDS = {'and', 'or', 'not'}


class PredicateError(ConfigsysError, ValueError):
    '''A malformed `when:` expression (also a ValueError for back-compat).'''


# -- AST ------------------------------------------------------------------

class Or:
    def __init__(self, terms):
        self.terms = terms

    def eval(self, ctx):
        return any(t.eval(ctx) for t in self.terms)


class And:
    def __init__(self, terms):
        self.terms = terms

    def eval(self, ctx):
        return all(t.eval(ctx) for t in self.terms)


class Not:
    def __init__(self, term):
        self.term = term

    def eval(self, ctx):
        return not self.term.eval(ctx)


class Os:
    def __init__(self, name, op=None, version=None):
        self.name = name
        self.op = op
        self.version = version          # a version tuple, or None for a bare atom

    def eval(self, ctx):
        # A versioned atom whose name isn't an OS block in this lineage is a version FACET
        # (`cuda >= 12`): compare the detected facet version. Absent facet -> never matches.
        if self.op is not None and self.name not in ctx.lineage and ctx.has_version_facet(self.name):
            v = ctx.facet_version(self.name)
            return v is not None and _CMP[self.op](v, self.version)
        if self.name not in ctx.lineage:
            return False
        if self.op is None:
            return True                 # bare atom: subtree membership only
        if ctx.scale_root_of(self.name) != ctx.system_scale_root:
            return False                # versioned atom on a foreign scale never matches
        return ctx.version is not None and _CMP[self.op](ctx.version, self.version)


class Categorical:
    '''A detected categorical dimension `ns:value` — cpu (ns='cpu') or a declared facet
    (ns='gpu', ...). Matches when the machine's value-set for that namespace intersects.'''
    def __init__(self, ns, values):
        self.ns = ns
        self.values = frozenset(values)

    def eval(self, ctx):
        return bool(self.values & ctx.categorical(self.ns))


def Cpu(cpus):
    '''Back-compat constructor: `cpu:` is just the categorical facet named 'cpu'.'''
    return Categorical('cpu', cpus)


def os_names(pred):
    '''Every OS block name a predicate's atoms reference (for validation — an unknown one
    is almost always a typo, since a `when:` naming a nonexistent OS silently never matches).'''
    out = set()

    def walk(p):
        if isinstance(p, Os):
            out.add(p.name)
        elif isinstance(p, Not):
            walk(p.term)
        elif isinstance(p, (And, Or)):
            for t in p.terms:
                walk(t)

    walk(pred)
    return out


# -- context --------------------------------------------------------------

class Context:
    '''A machine: OS lineage (leaf-first, from the cascade), version, cpu, and which
    blocks are version scale-roots.'''

    def __init__(self, lineage, version=None, cpu=None, scale_roots=(),
                 facets_cat=None, facets_ver=None):
        self.lineage = list(lineage)
        self.version = parse_version(version) if isinstance(version, str) else version
        self.cpu = cpu
        self.scale_roots = set(scale_roots)
        # detected environment facets. categorical: {ns -> frozenset(tags)} (cpu folds in here);
        # versioned: {name -> version tuple}. Absent = a `when:` atom over it is simply false.
        self.facets_cat = {ns: frozenset(v) for ns, v in (facets_cat or {}).items()}
        if cpu is not None:
            self.facets_cat.setdefault('cpu', frozenset([cpu]))
        self.facets_ver = {n: (parse_version(v) if isinstance(v, str) else v)
                           for n, v in (facets_ver or {}).items()}

    def categorical(self, ns):
        '''The machine's tag-set for a categorical namespace (cpu/gpu/…); empty if undetected.'''
        return self.facets_cat.get(ns, frozenset())

    def has_version_facet(self, name):
        return name in self.facets_ver

    def facet_version(self, name):
        return self.facets_ver.get(name)

    @property
    def system_scale_root(self):
        return self.scale_root_of(self.lineage[0]) if self.lineage else None

    def scale_root_of(self, name):
        '''Nearest scale-root walking from `name` toward the root (itself if it is one).'''
        if name not in self.lineage:
            return None
        for n in self.lineage[self.lineage.index(name):]:
            if n in self.scale_roots:
                return n
        return None


# -- parser ---------------------------------------------------------------

def _tokenize(text):
    toks, i = [], 0
    while i < len(text):
        m = _TOKEN.match(text, i)
        if not m:
            raise PredicateError(f'bad token in when: {text!r} at {text[i:]!r}')
        i = m.end()
        kind = m.lastgroup
        if kind == 'ws':
            continue
        toks.append((kind, m.group()))
    return toks


class _Parser:
    def __init__(self, toks, text):
        self.toks = toks
        self.text = text
        self.i = 0

    def _peek(self):
        return self.toks[self.i] if self.i < len(self.toks) else (None, None)

    def _next(self):
        t = self._peek()
        self.i += 1
        return t

    def parse(self):
        node = self._or()
        if self.i != len(self.toks):
            raise PredicateError(f'trailing tokens in when: {self.text!r}')
        return node

    def _or(self):
        terms = [self._and()]
        while self._peek() == ('ident', 'or'):
            self._next()
            terms.append(self._and())
        return terms[0] if len(terms) == 1 else Or(terms)

    def _and(self):
        terms = [self._not()]
        while self._peek() == ('ident', 'and'):
            self._next()
            terms.append(self._not())
        return terms[0] if len(terms) == 1 else And(terms)

    def _not(self):
        if self._peek() == ('ident', 'not'):
            self._next()
            return Not(self._not())
        return self._atom()

    def _atom(self):
        kind, val = self._peek()
        if kind == 'lparen':
            self._next()
            node = self._or()
            if self._next()[0] != 'rparen':
                raise PredicateError(f'missing ) in when: {self.text!r}')
            return node
        if kind != 'ident' or val in _KEYWORDS:
            raise PredicateError(f'expected an atom in when: {self.text!r}, got {val!r}')
        self._next()
        nkind, nval = self._peek()
        if nkind == 'colon':                    # `ns:value` / `ns:[…]` — cpu or a categorical facet
            return self._categorical(val)
        if nkind == 'cmp':                      # `name op version` — OS block or a version facet
            self._next()
            vkind, vval = self._next()
            if vkind != 'version':
                raise PredicateError(f'expected a version after {nval} in {self.text!r}')
            return Os(val, nval, parse_version(vval))
        return Os(val)                          # bare OS subtree atom

    def _categorical(self, ns):
        if self._next()[0] != 'colon':
            raise PredicateError(f'expected `{ns}:` in when: {self.text!r}')
        kind, val = self._next()
        if kind == 'ident':
            return Categorical(ns, [val])
        if kind != 'lbrack':
            raise PredicateError(f'expected a value or [ after `{ns}:` in when: {self.text!r}')
        vals = []
        while True:
            k, v = self._next()
            if k == 'rbrack':
                break
            if k == 'comma':
                continue
            if k != 'ident':
                raise PredicateError(f'bad `{ns}:` list in when: {self.text!r}')
            vals.append(v)
        return Categorical(ns, vals)


ALWAYS = And([])   # empty conjunction is vacuously true — the "no when:" default


def parse(text):
    if text is None or not text.strip():
        return ALWAYS
    return _Parser(_tokenize(text), text).parse()


# -- specificity + static ambiguity (set inclusion, decided on a finite grid) ----
#
# A predicate's match-set is decided over the universe of possible machines, which is
# finite once discretized: OS is a finite set of blocks (any block can be the detected
# system); cpu is the finitely-many mentioned cpus plus one "other"; and the version
# axis, though dense, is piecewise-constant — it only changes at the boundaries the
# predicates mention, so three sample points per boundary (just below / at / just above)
# capture every distinguishable region. Each predicate reduces to a boolean vector per
# (os, cpu) cell, and set inclusion / overlap become vector compares. or/not/versioned
# atoms all fall out for free.

_SENTINEL_CPU = '\x00other'


def _collect(preds, cascade):
    '''Discretize the grid dimensions a set of predicates mentions:
       cat_dims: {ns -> [values…, sentinel]}   categorical facets (cpu, gpu, …)
       vaxes:    {axis -> [samples]}            version axes; axis None = the OS version, a facet
                                                name = that version facet. Each mentioned boundary
                                                -> three samples (just below / at / just above).'''
    cat, vbounds = {}, {}

    def walk(p):
        if isinstance(p, (Or, And)):
            for t in p.terms:
                walk(t)
        elif isinstance(p, Not):
            walk(p.term)
        elif isinstance(p, Categorical):
            cat.setdefault(p.ns, set()).update(p.values)
        elif isinstance(p, Os) and p.version is not None:
            axis = None if p.name in cascade.blocks else p.name   # OS version vs a version facet
            vbounds.setdefault(axis, set()).add(p.version)

    for p in preds:
        walk(p)
    cat_dims = {ns: sorted(vals) + [_SENTINEL_CPU] for ns, vals in cat.items()}
    vaxes = {axis: sorted({(b, e) for b in bs for e in (-1, 0, 1)}) for axis, bs in vbounds.items()}
    vaxes.setdefault(None, [((0,), 0)])           # the OS version axis is always present
    return cat_dims, vaxes


def _scale_root(name, lineage, scale_roots):
    if name not in lineage:
        return None
    for n in lineage[lineage.index(name):]:
        if n in scale_roots:
            return n
    return None


def _cmp_sample(op, sample, v):
    b, eps = sample                        # sample = (version tuple, eps in {-1,0,+1})
    pos = -1 if b < v else (1 if b > v else eps)   # <0 below v, 0 at v, >0 above v
    if op == '<':
        return pos < 0
    if op == '<=':
        return pos <= 0
    if op == '>':
        return pos > 0
    if op == '>=':
        return pos >= 0
    return pos == 0                        # '=' / '=='


def _holds(pred, lineage, sroot_leaf, scale_roots, blocks, cat_assign, ver_assign):
    '''Does `pred` hold in one fully-concrete cell? `cat_assign` maps each categorical namespace
    to this cell's value; `ver_assign` maps each version axis (None=OS, or a facet name) to its
    sample. `blocks` = every OS block name (so a versioned atom naming a non-block is a facet).'''
    if isinstance(pred, Or):
        return any(_holds(t, lineage, sroot_leaf, scale_roots, blocks, cat_assign, ver_assign)
                   for t in pred.terms)
    if isinstance(pred, And):
        return all(_holds(t, lineage, sroot_leaf, scale_roots, blocks, cat_assign, ver_assign)
                   for t in pred.terms)
    if isinstance(pred, Not):
        return not _holds(pred.term, lineage, sroot_leaf, scale_roots, blocks, cat_assign, ver_assign)
    if isinstance(pred, Categorical):
        return cat_assign.get(pred.ns) in pred.values
    if isinstance(pred, Os):
        if pred.name in blocks:                       # an OS block atom
            if pred.name not in lineage:
                return False
            if pred.op is None:
                return True
            if _scale_root(pred.name, lineage, scale_roots) != sroot_leaf:
                return False
            return _cmp_sample(pred.op, ver_assign[None], pred.version)
        # name is not any OS block -> a version facet (only the versioned form is meaningful)
        if pred.op is None:
            return False
        s = ver_assign.get(pred.name)
        return s is not None and _cmp_sample(pred.op, s, pred.version)
    raise PredicateError(f'unknown predicate node {pred!r}')


def _cells(preds, cascade):
    '''Yield (lineage, sroot, blocks, cat_assign, ver_assign) for every fully-concrete grid cell:
       OS-leaf × each categorical dim's values × each version axis's samples. With no facets the
       product collapses to the old OS×cpu×OS-version grid, so existing behavior is unchanged.'''
    cat_dims, vaxes = _collect(preds, cascade)
    blocks = set(cascade.blocks)
    cat_names = sorted(cat_dims)
    ver_names = sorted(vaxes, key=lambda x: (x is not None, x or ''))
    cat_lists = [cat_dims[n] for n in cat_names]
    ver_lists = [vaxes[n] for n in ver_names]
    for leaf in cascade.blocks:
        lineage = cascade.lineage(leaf)
        sroot = _scale_root(leaf, lineage, cascade.scale_roots)
        for cat_combo in itertools.product(*cat_lists):
            cat_assign = dict(zip(cat_names, cat_combo))
            for ver_combo in itertools.product(*ver_lists):
                yield lineage, sroot, blocks, cat_assign, dict(zip(ver_names, ver_combo))


def subset(a, b, cascade):
    '''True if a's match-set ⊆ b's (a is at-least-as-specific as b), over all machines.'''
    sr = cascade.scale_roots
    for lineage, sroot, blocks, ca, va in _cells([a, b], cascade):
        if _holds(a, lineage, sroot, sr, blocks, ca, va) and not _holds(b, lineage, sroot, sr, blocks, ca, va):
            return False
    return True


def witness(a, b, cascade):
    '''A human-readable context where both a and b match, or None if disjoint.'''
    sr = cascade.scale_roots
    for lineage, sroot, blocks, ca, va in _cells([a, b], cascade):
        if _holds(a, lineage, sroot, sr, blocks, ca, va) and _holds(b, lineage, sroot, sr, blocks, ca, va):
            osver = va.get(None, ((0,), 0))
            parts = [lineage[0], 'any-version' if osver == ((0,), 0) else '.'.join(map(str, osver[0]))]
            cpu = ca.get('cpu', _SENTINEL_CPU)
            parts.append('any-cpu' if cpu == _SENTINEL_CPU else cpu)
            for ns, v in sorted(ca.items()):
                if ns != 'cpu' and v != _SENTINEL_CPU:
                    parts.append(f'{ns}:{v}')
            for name, s in sorted((kv for kv in va.items() if kv[0] is not None)):
                parts.append(f'{name} {".".join(map(str, s[0]))}')
            return ' '.join(parts)
    return None


def overlap(a, b, cascade):
    return witness(a, b, cascade) is not None


def comparable(a, b, cascade):
    return subset(a, b, cascade) or subset(b, a, cascade)


def most_specific(preds, cascade):
    '''From predicates already known to match a context, the unique most-specific one
    (⊆ every other), or raise if none/ambiguous (the static checker rules out the latter).'''
    winners = [p for p in preds if all(subset(p, o, cascade) for o in preds)]
    if len(winners) != 1:
        raise PredicateError(f'ambiguous selection among {len(preds)} matching bindings')
    return winners[0]
