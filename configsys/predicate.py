'''predicate.py — the v2 `when:` boolean DSL: parse, evaluate, and rank by specificity.

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

`not` is guarded to OS atoms by the (later) static ambiguity checker; evaluation here is
general. Specificity is set-inclusion over a per-dimension "box"; it currently supports
conjunctions of atoms (the "broad default + narrow overrides" idiom) and raises for
or/not, which the full checker slice will handle.
'''

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
        if self.name not in ctx.lineage:
            return False
        if self.op is None:
            return True                 # bare atom: subtree membership only
        if ctx.scale_root_of(self.name) != ctx.system_scale_root:
            return False                # versioned atom on a foreign scale never matches
        return ctx.version is not None and _CMP[self.op](ctx.version, self.version)


class Cpu:
    def __init__(self, cpus):
        self.cpus = frozenset(cpus)

    def eval(self, ctx):
        return ctx.cpu in self.cpus


# -- context --------------------------------------------------------------

class Context:
    '''A machine: OS lineage (leaf-first, from the cascade), version, cpu, and which
    blocks are version scale-roots.'''

    def __init__(self, lineage, version=None, cpu=None, scale_roots=()):
        self.lineage = list(lineage)
        self.version = parse_version(version) if isinstance(version, str) else version
        self.cpu = cpu
        self.scale_roots = set(scale_roots)

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
        if val == 'cpu':
            return self._cpu()
        # os atom, optionally versioned
        nkind, nval = self._peek()
        if nkind == 'cmp':
            self._next()
            vkind, vval = self._next()
            if vkind != 'version':
                raise PredicateError(f'expected a version after {nval} in {self.text!r}')
            return Os(val, nval, parse_version(vval))
        return Os(val)

    def _cpu(self):
        if self._next()[0] != 'colon':
            raise PredicateError(f'expected `cpu:` in when: {self.text!r}')
        kind, val = self._next()
        if kind == 'ident':
            return Cpu([val])
        if kind != 'lbrack':
            raise PredicateError(f'expected cpu value or [ in when: {self.text!r}')
        cpus = []
        while True:
            k, v = self._next()
            if k == 'rbrack':
                break
            if k == 'comma':
                continue
            if k != 'ident':
                raise PredicateError(f'bad cpu list in when: {self.text!r}')
            cpus.append(v)
        return Cpu(cpus)


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


def _collect(pred, bounds, cpus):
    if isinstance(pred, (Or, And)):
        for t in pred.terms:
            _collect(t, bounds, cpus)
    elif isinstance(pred, Not):
        _collect(pred.term, bounds, cpus)
    elif isinstance(pred, Cpu):
        cpus.update(pred.cpus)
    elif isinstance(pred, Os) and pred.version is not None:
        bounds.add(pred.version)


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


def _holds(pred, lineage, sroot_leaf, scale_roots, cpu, sample):
    if isinstance(pred, Or):
        return any(_holds(t, lineage, sroot_leaf, scale_roots, cpu, sample) for t in pred.terms)
    if isinstance(pred, And):
        return all(_holds(t, lineage, sroot_leaf, scale_roots, cpu, sample) for t in pred.terms)
    if isinstance(pred, Not):
        return not _holds(pred.term, lineage, sroot_leaf, scale_roots, cpu, sample)
    if isinstance(pred, Cpu):
        return cpu in pred.cpus
    if isinstance(pred, Os):
        if pred.name not in lineage:
            return False
        if pred.op is None:
            return True
        if _scale_root(pred.name, lineage, scale_roots) != sroot_leaf:
            return False
        return _cmp_sample(pred.op, sample, pred.version)
    raise PredicateError(f'unknown predicate node {pred!r}')


def _cells(preds, cascade):
    '''Yield (leaf, lineage, scale_root, cpu, samples) for every (os, cpu) grid cell.'''
    bounds, cpus = set(), set()
    for p in preds:
        _collect(p, bounds, cpus)
    cpu_vals = sorted(cpus) + [_SENTINEL_CPU]
    samples = {(b, e) for b in bounds for e in (-1, 0, 1)} or {((0,), 0)}
    for leaf in cascade.blocks:
        lineage = cascade.lineage(leaf)
        sroot = _scale_root(leaf, lineage, cascade.scale_roots)
        for cpu in cpu_vals:
            yield leaf, lineage, sroot, cpu, samples


def _vec(pred, lineage, sroot, scale_roots, cpu, samples):
    return frozenset(s for s in samples
                     if _holds(pred, lineage, sroot, scale_roots, cpu, s))


def subset(a, b, cascade):
    '''True if a's match-set ⊆ b's (a is at-least-as-specific as b), over all machines.'''
    sr = cascade.scale_roots
    for _leaf, lineage, sroot, cpu, samples in _cells([a, b], cascade):
        if not _vec(a, lineage, sroot, sr, cpu, samples) <= _vec(b, lineage, sroot, sr, cpu, samples):
            return False
    return True


def witness(a, b, cascade):
    '''A human-readable context where both a and b match, or None if disjoint.'''
    sr = cascade.scale_roots
    for leaf, lineage, sroot, cpu, samples in _cells([a, b], cascade):
        for s in samples:
            if _holds(a, lineage, sroot, sr, cpu, s) and _holds(b, lineage, sroot, sr, cpu, s):
                ver = '.'.join(map(str, s[0])) if s != ((0,), 0) else 'any-version'
                return f'{leaf} {ver} {"any-cpu" if cpu == _SENTINEL_CPU else cpu}'
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
