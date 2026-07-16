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

from ..osversion import parse_version

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


class PredicateError(ValueError):
    pass


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


# -- specificity (set-inclusion over per-dimension boxes) -----------------

class Box:
    '''The match-set of a conjunctive predicate as (os subtree, version constraint, cpu
    set). None on any dimension means "the whole axis".'''

    def __init__(self, os=None, version=None, cpu=None):
        self.os = os                    # os block name (subtree root)
        self.version = version          # (op, tuple) or None
        self.cpu = cpu                  # frozenset or None


def box(pred):
    '''Reduce a conjunction-of-atoms predicate to a Box. Raises for or/not (handled by
    the full ambiguity-checker slice).'''
    b = Box()
    for atom in _conjuncts(pred):
        if isinstance(atom, Os):
            if b.os is not None:
                raise NotImplementedError('multiple OS atoms in one conjunction')
            b.os = atom.name
            if atom.op is not None:
                b.version = (atom.op, atom.version)
        elif isinstance(atom, Cpu):
            b.cpu = atom.cpus if b.cpu is None else (b.cpu & atom.cpus)
        else:
            raise NotImplementedError('specificity for or/not is a later slice')
    return b


def _conjuncts(pred):
    if isinstance(pred, And):
        out = []
        for t in pred.terms:
            out.extend(_conjuncts(t))
        return out
    if isinstance(pred, (Or, Not)):
        raise NotImplementedError('specificity for or/not is a later slice')
    return [pred]


def box_subset(a, b, is_descendant):
    '''True if a's match-set ⊆ b's. `is_descendant(x, y)` = "y is ancestor-or-self of x"
    in the OS cascade (i.e. x's subtree ⊆ y's subtree).'''
    if b.os is not None and (a.os is None or not is_descendant(a.os, b.os)):
        return False
    if b.cpu is not None and (a.cpu is None or not a.cpu <= b.cpu):
        return False
    if b.version is not None and a.version != b.version:
        return False                    # coarse for now; interval algebra is a later slice
    return True


def most_specific(preds, is_descendant):
    '''From predicates already known to match, return the unique most-specific one (its
    box ⊆ every other's), or raise if none/ambiguous.'''
    boxes = [box(p) for p in preds]
    winners = [p for p, bp in zip(preds, boxes)
               if all(box_subset(bp, bo, is_descendant) for bo in boxes)]
    if len(winners) != 1:
        raise PredicateError(f'ambiguous selection among {len(preds)} matching bindings')
    return winners[0]
