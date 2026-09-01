#!/usr/bin/env python3
"""
uta_check.py — a small model checker for UPPAAL timed-automata XML models.

Implements UPPAAL semantics for the common modelling subset:
  - templates, locations (invariant / urgent / committed), init ref
  - transitions with guard / synchronisation (rendezvous, and broadcast) / assignment
  - declarations: const int, int, bool, clock, chan, broadcast chan
    (all variables are declared globally in the models we check; UPPAAL
     allows global declarations, so this stays valid UPPAAL)
  - queries:
        E<> p        -- exists a reachable state satisfying p
        A[] p        -- all reachable states satisfy p (zone-wide)
        A<> p        -- p is inevitable on every time-diverging run
        deadlock     -- as a predicate inside the above
    with p a boolean expression over ints, bools, clocks, and
    Process.location references (dotted identifiers), plus
    forall (i : int[lo,hi]) quantification in queries.

Zone representation: DBMs (difference-bound matrices) in the standard
half-bound encoding  2*value + (1 if strict).  Includes delay (up),
reset, canonical closure, and k-extrapolation per clock, so the zone
graph is finite.

Intended to verify the same properties UPPAAL's verifyta would verify
on the same .xml files (verifyta parses these files; it needs an
academic license key to actually run).
"""

import re
import sys
import xml.etree.ElementTree as ET
from collections import deque

INF = 10 ** 9


# --------------------------------------------------------------------------
# Expression language
# --------------------------------------------------------------------------

TOKEN_RE = re.compile(r"""
    \s*(?:
      (?P<num>\d+)
    | (?P<id>[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?)
    | (?P<op>\+\+|=>|&&|\|\||==|!=|<=|>=|[-+*/%()<!>=,{}\[\]:])
    )""", re.VERBOSE)


def tokenize(s):
    toks, i = [], 0
    while i < len(s):
        m = TOKEN_RE.match(s, i)
        if not m or not m.group().strip():
            if s[i:].strip() == '':
                break
            raise SyntaxError(f"bad token at {s[i:]!r}")
        i = m.end()
        if m.lastgroup == 'id' and m.group('id') in ('and', 'or', 'not', 'imply'):
            toks.append(('op', {'and': '&&', 'or': '||', 'not': '!',
                                'imply': '=>'}[m.group('id')]))
        elif m.lastgroup == 'num':
            toks.append(('num', int(m.group('num'))))
        elif m.lastgroup == 'id':
            toks.append(('id', m.group('id')))
        else:
            toks.append(('op', m.group('op')))
    return toks


class Parser:
    """Pratt parser -> nested tuples ('kind', ...)."""

    PREC = {'=>': 0, '||': 1, '&&': 2,
            '==': 4, '!=': 4, '<': 5, '<=': 5, '>': 5, '>=': 5,
            '+': 6, '-': 6, '*': 7, '/': 7, '%': 7}

    def __init__(self, toks):
        self.toks, self.i = toks, 0

    def peek(self):
        return self.toks[self.i] if self.i < len(self.toks) else (None, None)

    def next(self):
        t = self.peek()
        self.i += 1
        return t

    def expect(self, val):
        k, v = self.next()
        if v != val:
            raise SyntaxError(f"expected {val!r}, got {v!r}")

    def parse(self):
        e = self.parse_binary(0)
        if self.i != len(self.toks):
            raise SyntaxError(f"trailing tokens {self.toks[self.i:]!r}")
        return e

    def parse_binary(self, minprec):
        left = self.parse_unary()
        while True:
            k, v = self.peek()
            if k == 'op' and v in self.PREC and self.PREC[v] >= minprec:
                self.next()
                right = self.parse_binary(self.PREC[v] + 1)
                if v == '=>':      # a imply b  ==  !a || b
                    left = ('bin', '||', ('not', left), right)
                else:
                    left = ('bin', v, left, right)
            else:
                return left

    def parse_unary(self):
        k, v = self.peek()
        if k == 'op' and v == '!':
            self.next()
            return ('not', self.parse_unary())
        if k == 'op' and v == '-':
            self.next()
            return ('neg', self.parse_unary())
        return self.parse_primary()

    def parse_primary(self):
        k, v = self.next()
        if k == 'num':
            return ('num', v)
        if k == 'id':
            return ('id', v)
        if k == 'op' and v == '(':
            e = self.parse_binary(0)
            self.expect(')')
            return e
        raise SyntaxError(f"unexpected token {v!r}")


def parse_expr(s):
    return Parser(tokenize(s)).parse()


# --------------------------------------------------------------------------
# Declarations
# --------------------------------------------------------------------------

DECL_RE = re.compile(
    r"^\s*(?:(const)\s+)?(int|bool|clock|chan|broadcast\s+chan)\s+"
    r"([A-Za-z_][A-Za-z0-9_]*)\s*(?:=\s*([^;]+))?\s*;\s*$")


class Declarations:
    def __init__(self):
        self.consts = {}      # name -> int (const int with literal init)
        self.ints = {}        # name -> init value
        self.bools = {}       # name -> init value
        self.clocks = []      # ordered list of clock names
        self.clock_index = {}  # name -> index (1-based, 0 is the zero clock)
        self.chans = set()    # rendezvous channels
        self.broadcast = set()

    def add(self, text):
        text = re.sub(r'/\*.*?\*/', '', text, flags=re.S)
        text = re.sub(r'//[^\n]*', '', text)
        for stmt in [s for s in text.split(';') if s.strip()]:
            m = DECL_RE.match(stmt.strip() + ';')
            if not m:
                raise SyntaxError(f"unsupported declaration: {stmt.strip()!r}")
            is_const, typ, name, init = m.groups()
            typ = typ.strip()
            if typ == 'int' or typ == 'const':
                pass
            if typ == 'int':
                val = eval_int(init, self.consts) if init else 0
                if is_const:
                    self.consts[name] = val
                else:
                    self.ints[name] = val
            elif typ == 'bool':
                val = (init.strip() == 'true') if init else False
                if is_const:
                    self.consts[name] = 1 if val else 0
                else:
                    self.bools[name] = val
            elif typ == 'clock':
                self.clocks.append(name)
                self.clock_index[name] = len(self.clocks)
            elif typ in ('chan', 'broadcast chan'):
                (self.broadcast if typ == 'broadcast chan' else self.chans).add(name)
            else:
                raise SyntaxError(f"bad type {typ!r}")

    def clock_count(self):
        return len(self.clocks)


def eval_int(expr, consts):
    """Evaluate an integer expression over constants only."""
    def ev(node):
        if node[0] == 'num':
            return node[1]
        if node[0] == 'id':
            if node[1] in consts:
                return consts[node[1]]
            raise SyntaxError(f"unknown constant {node[1]!r} in int expr")
        if node[0] == 'neg':
            return -ev(node[1])
        if node[0] == 'bin':
            a, b = ev(node[2]), ev(node[3])
            return {'+': a + b, '-': a - b, '*': a * b,
                    '/': a // b, '%': a % b}[node[1]]
        raise SyntaxError("bad int expression")
    return ev(parse_expr(expr))


# --------------------------------------------------------------------------
# DBM
# --------------------------------------------------------------------------

class DBM:
    """n = number of clocks; matrix n+1 square. bound encoding:
       b = 2*v + (1 if strict).  dbm[i][j] upper bound on x_i - x_j.
       Row/col 0 is the zero clock."""

    __slots__ = ('n', 'm')

    def __init__(self, n, zero=False):
        self.n = n
        if zero:
            self.m = self._full(n, 0)
        else:
            self.m = self._full(n, INF)

    @staticmethod
    def _full(n, diag):
        return [[0 if i == j else INF for j in range(n + 1)] for i in range(n + 1)]

    @staticmethod
    def zero_dbm(n):
        d = DBM(n)
        for i in range(n + 1):
            for j in range(n + 1):
                d.m[i][j] = 0
        return d

    def copy(self):
        d = DBM(self.n)
        d.m = [row[:] for row in self.m]
        return d

    def consistent(self):
        return all(self.m[i][j] + self.m[j][i] >= 0
                   for i in range(self.n + 1) for j in range(self.n + 1))

    def close(self):
        n = self.n
        m = self.m
        for k in range(n + 1):
            mk = m[k]
            for i in range(n + 1):
                mik = m[i][k]
                if mik == INF:
                    continue
                mi = m[i]
                for j in range(n + 1):
                    v = mik + mk[j]
                    if v < mi[j]:
                        mi[j] = v
        return self

    def constrain(self, i, j, bound):
        """Add x_i - x_j <= bound (encoded)."""
        if bound < self.m[i][j]:
            self.m[i][j] = bound
            self.close()
        return self

    def up(self):
        """Delay: remove upper bounds on all clocks."""
        for i in range(1, self.n + 1):
            self.m[i][0] = INF
        return self.close()

    def free_unbounded_lower(self):
        pass

    def reset(self, x):
        """Reset clock x (1-based index) to 0."""
        m = self.m
        for i in range(self.n + 1):
            m[i][x] = (m[i][0] if i != x else 0)
        for j in range(self.n + 1):
            m[x][j] = m[0][j]
        m[x][x] = 0
        m[x][0] = 0
        return self.close()

    def knorm(self, kmax):
        """k-extrapolation (Behrmann et al.): every guard and invariant
        constant of the model is <= kmax, so clock values above kmax are
        indistinguishable to the automaton.  Upper bounds beyond kmax are
        raised to INF (time may continue); lower bounds and difference
        bounds beyond kmax collapse to the kmax level so the zone space
        stays finite.  Sound: never cuts time a guard could still see."""
        n = self.n
        m = self.m
        for i in range(1, n + 1):
            k = 2 * kmax[i - 1] + 1        # bound: x > kmax (strict)
            if m[i][0] > k:
                m[i][0] = INF              # x_i may run past kmax
            if m[0][i] < -k:
                m[0][i] = -(2 * kmax[i - 1])   # x_i >= kmax, collapse
        for i in range(1, n + 1):
            ki = kmax[i - 1]
            for j in range(1, n + 1):
                if i == j:
                    continue
                kj = kmax[j - 1]
                kk = 2 * max(ki, kj) + 1
                if m[i][j] > kk:
                    m[i][j] = INF
                elif m[i][j] < -kk:
                    m[i][j] = -(2 * kj + 1)    # x_j - x_i > kj, collapse
        return self.close()

    def key(self):
        return tuple(tuple(r) for r in self.m)

    def is_unbounded_delay(self):
        """True if time can pass without limit (all clock upper bounds INF)."""
        return all(self.m[i][0] == INF for i in range(1, self.n + 1))

    def entailed(self, i, j, bound):
        """D holds x_i - x_j <= bound ?"""
        return self.m[i][j] <= bound

    def may_satisfy(self, ast, env, sys_):
        """D ∧ p satisfiable?  (for clock-free p this is exact eval)"""
        return zone_may(ast, env, sys_, self)

    def all_satisfy(self, ast, env, sys_):
        """D ⊨ p  (all clock valuations in D satisfy p)?"""
        return zone_all(ast, env, sys_, self)


# The generic zone-level constraint handling above only needs the atomic
# comparison case, so it is done directly in may_satisfy via a dedicated
# walker below.

def expr_clocks(ast, sys_):
    """Clock names referenced in an expression."""
    out = set()
    def walk(a):
        if not isinstance(a, tuple):
            return
        if a[0] == 'id' and a[1] in sys_.decl.clock_index:
            out.add(a[1])
        for x in a[1:]:
            if isinstance(x, tuple):
                walk(x)
            elif isinstance(x, str):
                pass
    walk(ast)
    return out


# --------------------------------------------------------------------------
# Expression evaluation over (zone, discrete env).  Clock comparisons go
# through the zone; everything else evaluates on discrete variables.
# --------------------------------------------------------------------------

class EvalContext:
    def __init__(self, zone, env, sys_):
        self.zone, self.env, self.sys = zone, env, sys_


def eval_bool(ast, env, sys_, zone=None):
    return _eval(ast, env, sys_, zone)[0]


def _eval(ast, env, sys_, zone):
    """Returns (value, is_clock_bound_info).  For comparisons involving
    clocks we compute truth over the whole zone when zone is None
    (discrete eval) and otherwise zone-wide truth via satisfaction of
    the negated constraint."""
    kind = ast[0]
    if kind == 'num':
        return ast[1], False
    if kind == 'id':
        name = ast[1]
        if name == 'true':
            return True, False
        if name == 'false':
            return False, False
        if '.' in name:
            proc, loc = name.split('.', 1)
            return env.get(('loc', proc, loc), False), False
        if name in env:
            return env[name], False
        if name in sys_.decl.consts:
            return sys_.decl.consts[name], False
        raise NameError(name)
    if kind == 'not':
        v, _ = _eval(ast[1], env, sys_, zone)
        return (not v), False
    if kind == 'neg':
        v, _ = _eval(ast[1], env, sys_, zone)
        return -v, False
    if kind == 'bin':
        op = ast[1]
        lval, lclock = _eval(ast[2], env, sys_, zone)
        rval, rclock = _eval(ast[3], env, sys_, zone)
        if op in ('&&', '||'):
            return ((lval and rval) if op == '&&' else (lval or rval)), False
        # arithmetic must not involve clocks
        if lclock or rclock:
            if op in ('+', '-') and (lclock != rclock):
                # clock +/- int  -> linear clock expression; handle in compare
                return ('clockexpr', ast), True
            raise ValueError(f"clock in arithmetic op {op}")
        if op == '+':
            return lval + rval, False
        if op == '-':
            return lval - rval, False
        if op == '*':
            return lval * rval, False
        if op == '/':
            return lval // rval, False
        if op == '%':
            return lval % rval, False
        # comparisons
        if lclock or rclock:
            return zone_compare(op, ast, env, sys_, zone), True
        if op == '<':
            return lval < rval, False
        if op == '<=':
            return lval <= rval, False
        if op == '>':
            return lval > rval, False
        if op == '>=':
            return lval >= rval, False
        if op == '==':
            return lval == rval, False
        if op == '!=':
            return lval != rval, False
        raise ValueError(op)
    raise ValueError(kind)


def _clock_term(ast, env, sys_):
    """Return (clock_index, coeff, int_offset) for t, t+c, c-t etc.
    Supports only clock <op> const patterns."""
    kind = ast[0]
    if kind == 'id' and ast[1] in sys_.decl.clock_index:
        return sys_.decl.clock_index[ast[1]], 1, 0
    if kind == 'num':
        return 0, 0, ast[1]
    if kind == 'neg':
        c, k, off = _clock_term(ast[1], env, sys_)
        return c, -k, -off
    if kind == 'bin' and ast[1] in ('+', '-'):
        cl, kl, ol = _clock_term(ast[2], env, sys_)
        cr, kr, or_ = _clock_term(ast[3], env, sys_)
        if kl != 0 and kr != 0:
            raise ValueError("clock - clock comparison unsupported")
        if kl != 0:
            return cl, kl, ol + (or_ if ast[1] == '+' else -or_)
        return cr, kr * (1 if ast[1] == '+' else -1), or_ + ol * (-1 if ast[1] == '-' else 1)
    # int sub-expression
    return 0, 0, eval_int_expr(ast, env, sys_)


def eval_int_expr(ast, env, sys_):
    if ast[0] == 'num':
        return ast[1]
    if ast[0] == 'id':
        name = ast[1]
        if name == 'true':
            return 1
        if name == 'false':
            return 0
        if name in env:
            return env[name]
        if name in sys_.decl.consts:
            return sys_.decl.consts[name]
        raise NameError(name)
    if ast[0] == 'neg':
        return -eval_int_expr(ast[1], env, sys_)
    if ast[0] == 'not':
        return 0 if eval_bool(ast[1], env, sys_) else 1
    if ast[0] == 'bin':
        op = ast[1]
        if op == '&&':
            return 1 if (eval_int_expr(ast[2], env, sys_) and eval_int_expr(ast[3], env, sys_)) else 0
        if op == '||':
            return 1 if (eval_int_expr(ast[2], env, sys_) or eval_int_expr(ast[3], env, sys_)) else 0
        a = eval_int_expr(ast[2], env, sys_)
        b = eval_int_expr(ast[3], env, sys_)
        return {'+': lambda: a + b, '-': lambda: a - b, '*': lambda: a * b,
                '/': lambda: a // b if b else 0, '%': lambda: a % b if b else 0,
                '<': lambda: int(a < b), '<=': lambda: int(a <= b),
                '>': lambda: int(a > b), '>=': lambda: int(a >= b),
                '==': lambda: int(a == b), '!=': lambda: int(a != b)}[op]()
    raise ValueError(ast)


def zone_compare(op, ast, env, sys_, zone):
    """Zone-wide truth of a clock comparison.  Without a zone (discrete
    pre-check), we cannot decide -> return True (may) so guards get
    properly re-tested with the zone."""
    if zone is None:
        return True
    # LHS/RHS as clock-terms
    cl, kl, ol = _clock_term(ast[2], env, sys_)
    cr, kr, orr = _clock_term(ast[3], env, sys_)
    if kl == 0 and kr == 0:
        raise ValueError("no clock in clock comparison")
    if kl != 0 and kr != 0:
        raise ValueError("clock-clock comparisons must have coeff ±1 each")
    if kl != 0:
        # k*x_c + ol  OP  -kr*x_c' + orr  -> normalise to x_c - x_c' <= / >=
        # only k=±1 supported
        if kl != 1:
            raise ValueError("clock coeff must be 1")
        other, sign = (0, 1) if kr == 0 else (cr, 1)
        # x_c + ol OP orr   (kr==0)
        if kr == 0:
            diff_bound = orr - ol        # x_c <= diff_bound for '<='
            i, j = cl, 0
            if op == '<=':
                return zone.entailed(i, j, 2 * diff_bound)
            if op == '<':
                return zone.entailed(i, j, 2 * diff_bound - 1)
            if op == '>=':
                # x_c >= c  <=>  -x_c <= -c  <=>  dbm[0][c] <= -2c
                return zone.entailed(j, i, -2 * diff_bound)
            if op == '>':
                return zone.entailed(j, i, -2 * diff_bound - 1)
            if op == '==':
                return (zone.entailed(i, j, 2 * diff_bound)
                        and zone.entailed(j, i, -2 * diff_bound))
            if op == '!=':
                return not (zone.entailed(i, j, 2 * diff_bound)
                            and zone.entailed(j, i, -2 * diff_bound))
        else:
            # x_c - x_c' (both clocks, coeffs 1, rhs offset)
            if kr != -1:
                raise ValueError("clock-clock coeff mismatch")
            i, j = cl, cr
            b = orr - ol
            if op == '<=':
                return zone.entailed(i, j, 2 * b)
            if op == '<':
                return zone.entailed(i, j, 2 * b - 1)
            if op == '>=':
                return zone.entailed(j, i, -2 * b)
            if op == '>':
                return zone.entailed(j, i, -2 * b - 1)
            if op == '==':
                return (zone.entailed(i, j, 2 * b) and zone.entailed(j, i, -2 * b))
            if op == '!=':
                return not (zone.entailed(i, j, 2 * b) and zone.entailed(j, i, -2 * b))
    if kr != 0:
        # constant OP clock  -- flip
        flip = {'<': '>', '<=': '>=', '>': '<', '>=': '<=', '==': '==', '!=': '!='}
        return zone_compare(flip[op], ('bin', op, ast[3], ast[2]), env, sys_, zone)
    raise ValueError("unreachable compare")


def zone_may(ast, env, sys_, zone):
    """D ∧ p satisfiable (exact for our atom set)."""
    if expr_clocks(ast, sys_) == set():
        return eval_bool(ast, env, sys_)
    kind = ast[0]
    if kind == 'not':
        return not zone_all(ast[1], env, sys_, zone)
    if kind == 'bin' and ast[1] == '&&':
        # satisfiable for all conjuncts on a COMMON zone: constrain sequentially
        d = zone.copy()
        for atom in atoms_of(ast):
            if not _atom_constrain(atom, d, env, sys_):
                # clock-free atom inside a clocked conjunction: evaluate
                if not eval_bool(atom, env, sys_):
                    return False
        return d.consistent()
    if kind == 'bin' and ast[1] == '||':
        return zone_may(ast[2], env, sys_, zone) or zone_may(ast[3], env, sys_, zone)
    # single atom
    d = zone.copy()
    if not _atom_constrain(ast, d, env, sys_):
        return eval_bool(ast, env, sys_)
    return d.consistent()


def atoms_of(ast):
    """Split top-level && chain into atoms."""
    if ast[0] == 'bin' and ast[1] == '&&':
        return atoms_of(ast[2]) + atoms_of(ast[3])
    return [ast]


def _atom_constrain(atom, d, env, sys_):
    """Constrain zone d so that the (positive, comparison) atom holds.
    Returns False if the atom is not a comparison or cannot constrain."""
    if atom[0] != 'bin' or atom[1] not in ('<', '<=', '>', '>=', '==', '!='):
        return False
    op = atom[1]
    cl, kl, ol = _clock_term(atom[2], env, sys_)
    cr, kr, orr = _clock_term(atom[3], env, sys_)
    if kl == 0 and kr == 0:
        return False
    if kl != 0 and kr == 0:
        if kl != 1:
            return False
        b = orr - ol
        if op == '<=':
            d.constrain(cl, 0, 2 * b)
        elif op == '<':
            d.constrain(cl, 0, 2 * b - 1)
        elif op == '>=':
            d.constrain(0, cl, -2 * b)
        elif op == '>':
            d.constrain(0, cl, -2 * b - 1)
        elif op == '==':
            d.constrain(cl, 0, 2 * b)
            d.constrain(0, cl, -2 * b)
        else:
            return False
        return True
    if kr != 0 and kl == 0:
        flip = {'<': '>', '<=': '>=', '>': '<', '>=': '<=', '==': '==', '!=': '!='}
        return _atom_constrain(('bin', flip[op], atom[3], atom[2]), d, env, sys_)
    return False


def zone_all(ast, env, sys_, zone):
    """D ⊨ ast (all valuations)."""
    if expr_clocks(ast, sys_) == set():
        return eval_bool(ast, env, sys_)
    kind = ast[0]
    if kind == 'not':
        return not zone_may(ast[1], env, sys_, zone)
    if kind == 'bin' and ast[1] == '&&':
        return zone_all(ast[2], env, sys_, zone) and zone_all(ast[3], env, sys_, zone)
    if kind == 'bin' and ast[1] == '||':
        return zone_all(ast[2], env, sys_, zone) or zone_all(ast[3], env, sys_, zone)
    # atom: D ∧ ¬atom unsatisfiable
    neg = _negate(ast)
    if neg is None:
        return eval_bool(ast, env, sys_)
    return not zone_may(neg, env, sys_, zone)


def _negate(atom):
    if atom[0] != 'bin' or atom[1] not in ('<', '<=', '>', '>=', '==', '!='):
        return None
    flip = {'<': '>=', '<=': '>', '>': '<=', '>=': '<', '==': '!=', '!=': '=='}
    return ('bin', flip[atom[1]], atom[2], atom[3])


# --------------------------------------------------------------------------
# System / processes
# --------------------------------------------------------------------------

class Location:
    __slots__ = ('name', 'invariant', 'urgent', 'committed')

    def __init__(self, name, invariant, urgent, committed):
        self.name, self.invariant, self.urgent, self.committed = name, invariant, urgent, committed


class Transition:
    __slots__ = ('src', 'tgt', 'guard', 'sync', 'assign')

    def __init__(self, src, tgt, guard, sync, assign):
        self.src, self.tgt, self.guard, self.sync, self.assign = src, tgt, guard, sync, assign


class Template:
    def __init__(self, name):
        self.name = name
        self.locations = {}   # id -> Location
        self.loc_by_name = {}  # name -> id
        self.init = None
        self.transitions = []  # list of Transition


class System:
    def __init__(self):
        self.decl = Declarations()
        self.templates = {}   # name -> Template
        self.instances = []  # (process_name, template_name)
        self.queries = []    # (formula_str, comment)

    def proc_template(self, proc):
        return self.templates[dict(self.instances)[proc]]


def load_model(path):
    tree = ET.parse(path)
    root = tree.getroot()
    sys_ = System()
    decl_el = root.find('declaration')
    if decl_el is not None:
        sys_.decl.add(decl_el.text or '')
    for tel in root.findall('template'):
        tname = tel.find('name').text
        t = Template(tname)
        for lel in tel.findall('location'):
            lid = lel.get('id')
            name_el = lel.find('name')
            name = name_el.text if name_el is not None else lid
            inv_el = lel.find('label[@kind="invariant"]')
            inv = parse_expr(inv_el.text) if inv_el is not None and inv_el.text else None
            urgent = lel.find('urgent') is not None
            committed = lel.find('committed') is not None
            t.locations[lid] = Location(name, inv, urgent, committed)
            t.loc_by_name[name] = lid
        init_el = tel.find('init')
        t.init = init_el.get('ref')
        for tr in tel.findall('transition'):
            guard_el = tr.find('label[@kind="guard"]')
            sync_el = tr.find('label[@kind="synchronisation"]')
            asg_el = tr.find('label[@kind="assignment"]')
            guard = parse_expr(guard_el.text) if guard_el is not None and guard_el.text else None
            sync = sync_el.text if sync_el is not None else None
            assign = asg_el.text if asg_el is not None else None
            t.transitions.append(Transition(
                tr.find('source').get('ref'), tr.find('target').get('ref'),
                guard, sync.strip() if sync else None,
                assign.strip() if assign else None))
        sys_.templates[tname] = t
    system_el = root.find('system')
    if system_el is None:
        raise SyntaxError("missing <system>")
    bindings = {}
    order = []
    for line in system_el.text.split(';'):
        line = line.strip()
        if not line or line.startswith('//'):
            continue
        if line.startswith('system '):
            order = [p.strip() for p in line[len('system '):].split(',')]
        else:
            mm = re.match(r'^(\w+)\s*=\s*(\w+)\s*(?:\(\s*\))?$', line)
            if mm:
                bindings[mm.group(1)] = mm.group(2)
            else:
                raise SyntaxError(f"bad system line {line!r}")
    if not order:
        order = list(bindings)
    for p in order:
        if p not in bindings:
            # "system P;" with no explicit binding: process name = template name
            bindings[p] = p
        sys_.instances.append((p, bindings[p]))
    qel = root.find('queries')
    if qel is not None:
        for q in qel.findall('query'):
            f = q.find('formula')
            c = q.find('comment')
            sys_.queries.append((f.text.strip() if f is not None and f.text else '',
                                 c.text.strip() if c is not None and c.text else ''))
    return sys_


# --------------------------------------------------------------------------
# State-space exploration
# --------------------------------------------------------------------------

class Checker:
    def __init__(self, sys_):
        self.sys = sys_
        self.procs = [p for p, _ in sys_.instances]
        self.templ = {p: sys_.templates[t] for p, t in sys_.instances}
        self.nclocks = sys_.decl.clock_count()
        # per-clock maximum constant, for extrapolation
        self.kmax = [0] * self.nclocks
        self._collect_kmax()
        self.states = []       # (locs tuple, env dict, DBM)
        self.state_index = {}  # key -> index
        self.succ = []         # successors: list of lists of (state_idx, label)
        self.parent = []       # BFS parent index for witnesses

    def _collect_kmax(self):
        for t in self.sys.templates.values():
            for loc in t.locations.values():
                if loc.invariant is not None:
                    for c in expr_clocks(loc.invariant, self.sys):
                        b = self._max_const(loc.invariant)
                        i = self.sys.decl.clock_index[c] - 1
                        self.kmax[i] = max(self.kmax[i], b)
            for tr in t.transitions:
                if tr.guard is not None:
                    for c in expr_clocks(tr.guard, self.sys):
                        i = self.sys.decl.clock_index[c] - 1
                        self.kmax[i] = max(self.kmax[i],
                                           self._max_const(tr.guard))
        # keep it generous but finite
        self.kmax = [max(2, k) for k in self.kmax]

    def _max_const(self, ast):
        best = [0]
        def walk(a):
            if not isinstance(a, tuple):
                return
            if a[0] == 'num':
                best[0] = max(best[0], a[1])
            elif a[0] == 'id' and a[1] in self.sys.decl.consts:
                best[0] = max(best[0], self.sys.decl.consts[a[1]])
            for x in a[1:]:
                if isinstance(x, tuple):
                    walk(x)
        walk(ast)
        return best[0]

    # ---- initial state -------------------------------------------------
    def initial(self):
        locs = tuple(self.templ[p].init for p in self.procs)
        env = {}
        for k, v in self.sys.decl.ints.items():
            env[k] = v
        for k, v in self.sys.decl.bools.items():
            env[k] = v
        # location propositions
        for p in self.procs:
            for name, lid in self.templ[p].loc_by_name.items():
                env[('loc', p, name)] = (lid == self.templ[p].init)
        d = DBM.zero_dbm(self.nclocks).close()
        d = self._inv_apply(locs, d, env)
        if d is None:
            raise RuntimeError("initial state violates invariant")
        return locs, env, d

    def _inv_apply(self, locs, d, env):
        d = d.copy()
        for p, lid in zip(self.procs, locs):
            loc = self.templ[p].locations[lid]
            if loc.invariant is not None:
                for atom in atoms_of(loc.invariant):
                    if not _atom_constrain(atom, d, env, self.sys):
                        raise RuntimeError(f"non-clock invariant atom {atom!r}")
        d.close()
        if not d.consistent():
            return None
        return d

    # ---- successors ------------------------------------------------------
    def successors(self, idx):
        locs, env, zone = self.states[idx]
        out = []
        any_committed = any(self.templ[p].locations[lid].committed
                            for p, lid in zip(self.procs, locs))
        # When some process is committed, only edges leaving committed
        # locations may fire -- but non-committed processes may join as
        # synchronisation partners of a committed mover.
        def may_join(initiator_committed, partner_committed):
            if not any_committed:
                return True
            return initiator_committed or partner_committed

        # discrete transitions
        for pi, (p, lid) in enumerate(zip(self.procs, locs)):
            loc = self.templ[p].locations[lid]
            if any_committed and not loc.committed:
                # may only join a committed process's sync — handled when
                # the committed process offers; standalone moves forbidden
                continue
            for tri, tr in enumerate(self.templ[p].transitions):
                if tr.src != lid:
                    continue
                if tr.sync is None:
                    if any_committed and not loc.committed:
                        continue
                    s = self._fire(idx, [(pi, tri)], locs, env, zone)
                    if s is not None:
                        out.append((s, f"{p}:{tr.src}->{tr.tgt}"))
                else:
                    chan, bang = self._parse_sync(tr.sync)
                    if chan in self.sys.decl.broadcast:
                        # every receiver process takes at most one edge;
                        # enumerate combinations (a receiver may also stay
                        # put only if it has no enabled edge -- UPPAAL
                        # broadcast semantics: all enabled receivers fire)
                        per_proc = []
                        for qi, q in enumerate(self.procs):
                            if qi == pi:
                                continue
                            opts = [(qi, qtri)
                                    for qtri, qtr in enumerate(self.templ[q].transitions)
                                    if qtr.src == locs[qi] and qtr.sync
                                    and self._parse_sync(qtr.sync) == (chan, False)]
                            if opts:
                                per_proc.append(opts)
                        combos = [[]]
                        for opts in per_proc:
                            combos = [c + [o] for c in combos for o in opts]
                        for extra in combos:
                            s = self._fire(idx, [(pi, tri)] + extra, locs, env, zone)
                            if s is not None:
                                out.append((s, tr.sync))
                    else:
                        want = (chan, not bang)
                        for qi, q in enumerate(self.procs):
                            if qi == pi:
                                continue
                            for qtri, qtr in enumerate(self.templ[q].transitions):
                                if qtr.src != locs[qi] or qtr.sync is None:
                                    continue
                                if self._parse_sync(qtr.sync) != want:
                                    continue
                                if not may_join(loc.committed,
                                                 self.templ[q].locations[locs[qi]].committed):
                                    continue
                                s = self._fire(idx, [(pi, tri), (qi, qtri)], locs, env, zone)
                                if s is not None:
                                    out.append((s, tr.sync))
        # delay
        can_delay = not any_committed and not any(
            self.templ[p].locations[lid].urgent or self.templ[p].locations[lid].committed
            for p, lid in zip(self.procs, locs))
        if can_delay:
            d = zone.copy().up()
            d2 = self._inv_apply(locs, d, env)
            if d2 is not None and d2.key() != zone.key():
                out.append((self._intern(locs, env, d2), 'delay'))
        return out

    def _parse_sync(self, s):
        return (s[:-1].strip(), s[-1] == '!')

    def _fire(self, idx, edges, locs, env, zone):
        """edges: list of (proc_index, trans_index) participating."""
        # Guards are evaluated at the firing instant: clock atoms CONSTRAIN
        # the successor zone (successor = D ∩ guard), clock-free atoms are
        # evaluated on the discrete variables.
        d = zone.copy()
        newenv = dict(env)
        for pi, tri in edges:
            tr = self.templ[self.procs[pi]].transitions[tri]
            if tr.guard is None:
                continue
            for atom in atoms_of(tr.guard):
                if expr_clocks(atom, self.sys) == set():
                    if not eval_bool(atom, newenv, self.sys):
                        return None
                else:
                    if not _atom_constrain(atom, d, newenv, self.sys):
                        return None
            if not d.consistent():
                return None
        newlocs = list(locs)
        for pi, tri in edges:
            tr = self.templ[self.procs[pi]].transitions[tri]
            if tr.assign:
                self._apply_assign(tr.assign, newenv, d)
            newlocs[pi] = tr.tgt
        newlocs = tuple(newlocs)
        d = self._inv_apply(newlocs, d, newenv)
        if d is None:
            return None
        self._update_loc_props(newlocs, newenv)
        return self._intern(newlocs, newenv, d)

    def _apply_assign(self, assign, env, d):
        for stmt in assign.split(','):
            stmt = stmt.strip()
            if not stmt:
                continue
            m = re.match(r'^(\w+)\s*(?:\+\+|:=|=)\s*(.+)$', stmt)
            if not m:
                raise SyntaxError(f"bad assignment {stmt!r}")
            name, rhs = m.group(1), m.group(2)
            if name in self.sys.decl.clock_index:
                val = eval_int_expr(parse_expr(rhs), env, self.sys)
                if val != 0:
                    raise ValueError("clocks can only be reset to 0")
                d.reset(self.sys.decl.clock_index[name])
            else:
                env[name] = eval_int_expr(parse_expr(rhs), env, self.sys)

    def _update_loc_props(self, locs, env):
        for p, lid in zip(self.procs, locs):
            tmpl = self.templ[p]
            for name, l in tmpl.loc_by_name.items():
                env[('loc', p, name)] = (l == lid)

    def _intern(self, locs, env, d):
        d.knorm(self.kmax)
        key = (locs, tuple(sorted((k, v) for k, v in env.items()
                                  if not isinstance(k, tuple))), d.key())
        if key in self.state_index:
            return self.state_index[key]
        self.states.append((locs, dict(env), d))
        self.succ.append(None)
        self.parent.append(None)
        i = len(self.states) - 1
        self.state_index[key] = i
        return i

    def explore(self):
        locs, env, d = self.initial()
        i0 = self._intern(locs, env, d)
        queue = deque([i0])
        while queue:
            i = queue.popleft()
            if self.succ[i] is None:
                self.succ[i] = self.successors(i)
                for j, _ in self.succ[i]:
                    if self.parent[j] is None and j != i0:
                        self.parent[j] = i
                    queue.append(j)
        return i0, len(self.states)

    # ---- deadlock ---------------------------------------------------------
    def is_deadlock(self, idx):
        locs, env, zone = self.states[idx]
        if self.succ[idx]:
            return False
        # no discrete successors: deadlock unless time can pass
        can_delay = not any(self.templ[p].locations[lid].urgent or
                            self.templ[p].locations[lid].committed
                            for p, lid in zip(self.procs, locs))
        if not can_delay:
            return True
        d = zone.copy().up()
        return self._inv_apply(locs, d, env) is None

    # ---- queries ----------------------------------------------------------
    def _expand_forall(self, ast):
        """Expand forall (i : int[lo,hi]) p  into a conjunction list."""
        s = self._forall_str(ast)
        return s

    def _forall_str(self, ast):
        return ast  # forall handled at string level before parsing

    def check_query(self, formula):
        formula = formula.strip()
        if formula == 'A[] not deadlock':
            for i in range(len(self.states)):
                if self.is_deadlock(i):
                    return ('A[]', (False, i))
            return ('A[]', (True, None))
        if formula == 'E<> deadlock' or formula == 'deadlock':
            return ('E<>', self._query_deadlock())
        # leads-to:  p --> q   (handled at string level, outside parens)
        depth, split = 0, None
        k = 0
        while k < len(formula) - 3:
            c = formula[k]
            if c == '(':
                depth += 1
            elif c == ')':
                depth -= 1
            elif (depth == 0 and formula[k:k + 3] == '-->'
                  and k > 0 and not (formula[k - 1].isalnum() or formula[k - 1] in '_.')):
                split = k
                break
            k += 1
        if split is not None:
            p_str = formula[:split].strip()
            q_str = formula[split + 3:].strip()
            if p_str.startswith('(') and p_str.endswith(')'):
                p_str = p_str[1:-1]
            if q_str.startswith('(') and q_str.endswith(')'):
                q_str = q_str[1:-1]
            return ('-->', self._query_leads_to([parse_expr(p_str)],
                                                [parse_expr(q_str)]))
        # forall expansion (string level)
        m = re.match(r'^(.*?)forall\s*\(\s*(\w+)\s*:\s*int\[(\d+)\s*,\s*(\d+)\]\s*\)\s*(.*)$', formula)
        bounds = None
        if m:
            prefix, var, lo, hi, rest = m.group(1), m.group(2), int(m.group(3)), int(m.group(4)), m.group(5)
            bounds = (prefix, var, lo, hi, rest)

        if formula.startswith('E<>'):
            body = formula[3:]
            variants = self._variants(body, bounds)
            return ('E<>', self._query_E(variants))
        if formula.startswith('A[]'):
            body = formula[3:]
            variants = self._variants(body, bounds)
            return ('A[]', self._query_A_box(variants))
        if formula.startswith('A<>'):
            body = formula[3:]
            variants = self._variants(body, bounds)
            return ('A<>', self._query_A_diamond(variants))
        raise SyntaxError(f"unsupported query {formula!r}")

    def _variants(self, body, bounds):
        if bounds is None:
            return [parse_expr(body)]
        prefix, var, lo, hi, rest = bounds
        out = []
        for v in range(lo, hi + 1):
            replaced = re.sub(rf'\b{var}\b', str(v), rest)
            out.append(parse_expr(replaced))
        return out

    def _query_E(self, asts):
        for i, (locs, env, zone) in enumerate(self.states):
            for ast in asts:
                if zone_may(ast, env, self.sys, zone):
                    return (True, i)
        return (False, None)

    def _query_A_box(self, asts):
        for i, (locs, env, zone) in enumerate(self.states):
            for ast in asts:
                if not zone_all(ast, env, self.sys, zone):
                    return (False, i)
        return (True, None)

    def _query_A_diamond(self, asts):
        """A<> p: fails if some reachable state may-violate p and lies on a
        cycle / can diverge avoiding p.  Exact for clock-free p."""
        violating = set()
        for i, (locs, env, zone) in enumerate(self.states):
            if not all(zone_all(ast, env, self.sys, zone) for ast in asts):
                violating.add(i)
        if not violating:
            return (True, None)
        # can time diverge while violating? (unbounded delay in a violating
        # state where delay is allowed at all)
        for i in violating:
            locs, env, zone = self.states[i]
            if any(self.templ[p].locations[lid].urgent or
                   self.templ[p].locations[lid].committed
                   for p, lid in zip(self.procs, locs)):
                continue
            d = zone.copy().up()
            d2 = self._inv_apply(locs, d, env)
            if d2 is not None and d2.is_unbounded_delay() and not zone_may_all(asts, env, self.sys, d2):
                return (False, i)
            if not self.succ[i] and self.is_deadlock(i):
                return (False, i)
        # cycle among violating states
        scc = self._find_cycle(violating)
        return (False, scc) if scc is not None else (True, None)

    def _query_deadlock(self):
        for i in range(len(self.states)):
            if self.is_deadlock(i):
                return (True, i)   # deadlock exists -> 'deadlock' E-query true
        return (False, None)

    def _query_leads_to(self, p_asts, q_asts):
        """p --> q: from every reachable state satisfying p, q is
        inevitable.  Computed as: no p-state belongs to V, where V is the
        greatest fixpoint of states from which some infinite run avoids q
        (a successor in V, a deadlock while avoiding q, or unbounded delay
        avoiding q)."""
        n = len(self.states)
        # may-delay info per state
        can_delay = []
        for i in range(n):
            locs, env, zone = self.states[i]
            ok = not any(self.templ[p].locations[lid].urgent or
                         self.templ[p].locations[lid].committed
                         for p, lid in zip(self.procs, locs))
            d = zone.copy().up() if ok else None
            d2 = self._inv_apply(locs, d, env) if d is not None else None
            diverges = (d2 is not None and d2.is_unbounded_delay()
                        and not zone_may_all(q_asts, env, self.sys, d2))
            can_delay.append(diverges)
        inV = [False] * n
        for i in range(n):
            locs, env, zone = self.states[i]
            if zone_all_multi(q_asts, env, self.sys, zone):
                continue
            if not self.succ[i] or can_delay[i]:
                inV[i] = True
        changed = True
        while changed:
            changed = False
            for i in range(n):
                if inV[i]:
                    continue
                locs, env, zone = self.states[i]
                if zone_all_multi(q_asts, env, self.sys, zone):
                    continue
                if any(inV[j] for j, _ in self.succ[i]):
                    inV[i] = True
                    changed = True
        for i in range(n):
            locs, env, zone = self.states[i]
            if zone_all_multi(p_asts, env, self.sys, zone) and inV[i]:
                return (False, i)
        return (True, None)

    def _find_cycle(self, sub):
        # Tarjan SCC over subgraph induced on 'sub'
        index_counter = [0]
        stack, lowlink, index, on_stack = [], {}, {}, {}
        sccs = []

        def strongconnect(v):
            index[v] = lowlink[v] = index_counter[0]
            index_counter[0] += 1
            stack.append(v)
            on_stack[v] = True
            for w, lbl in self.succ[v]:
                # A pure delay edge back to the same symbolic state does not
                # let time diverge (the invariant still bounds the clocks);
                # it cannot witness a liveness violation.
                if w == v and lbl == 'delay':
                    continue
                if w not in sub:
                    continue
                if w not in index:
                    strongconnect(w)
                    lowlink[v] = min(lowlink[v], lowlink[w])
                elif on_stack.get(w):
                    lowlink[v] = min(lowlink[v], index[w])
            if lowlink[v] == index[v]:
                comp = []
                while True:
                    w = stack.pop()
                    on_stack[w] = False
                    comp.append(w)
                    if w == v:
                        break
                sccs.append(comp)

        import sys as _sys
        _sys.setrecursionlimit(100000)
        for v in sub:
            if v not in index:
                strongconnect(v)
        for comp in sccs:
            if len(comp) > 1:
                return comp[0]
            v = comp[0]
            if any(w == v and lbl != 'delay' for w, lbl in self.succ[v]):
                return v
        return None

    # ---- witness ------------------------------------------------------------
    def witness(self, idx):
        path = []
        while idx is not None:
            path.append(idx)
            idx = self.parent[idx]
        path.reverse()
        return path

    def state_str(self, idx):
        locs, env, zone = self.states[idx]
        procs = ", ".join(f"{p}.{self.templ[p].locations[lid].name}"
                          for p, lid in zip(self.procs, locs))
        ints = ", ".join(f"{k}={v}" for k, v in env.items()
                         if not isinstance(k, tuple) and k in self.sys.decl.ints)
        return f"[{procs}] {ints}"


def zone_all_multi(asts, env, sys_, zone):
    return all(zone_all(ast, env, sys_, zone) for ast in asts)


def zone_may_all(asts, env, sys_, zone):
    return all(zone_all(ast, env, sys_, zone) for ast in asts)


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

def run(model_path, query_file=None):
    sys_ = load_model(model_path)
    print(f"model: {model_path}")
    print(f"processes: {', '.join(p for p, _ in sys_.instances)}   "
          f"clocks: {sys_.decl.clock_count()} ({', '.join(sys_.decl.clocks)})")
    ck = Checker(sys_)
    i0, nstates = ck.explore()
    print(f"zone-graph states: {nstates}")

    queries = []
    if query_file:
        for line in open(query_file):
            line = line.strip()
            if line and not line.startswith('//'):
                queries.append((line, ''))
    else:
        queries = sys_.queries

    results = []
    for formula, comment in queries:
        if not formula:
            continue
        kind, (holds, idx) = ck.check_query(formula)
        status = 'PASS' if ((holds and kind in ('A[]', 'A<>', '-->')) or
                            (holds and kind in ('E<>', 'deadlock'))) else 'FAIL'
        # E<> passing means property satisfied (reachable), reported as PASS
        if kind in ('E<>', 'deadlock'):
            status = 'PASS' if holds else 'FAIL'
        print(f"  {status}  {kind:4} {formula}    ({comment})")
        if not holds and kind == 'A[]':
            w = ck.witness(idx)
            print(f"        witness (violation) at: {ck.state_str(idx)}")
        if holds and kind in ('E<>', 'deadlock'):
            w = ck.witness(idx)
            print(f"        witness: {ck.state_str(idx)}")
        if not holds and kind in ('A<>', '-->'):
            w = ck.witness(idx)
            print(f"        counterexample loop at: {ck.state_str(idx)}")
        results.append((formula, kind, status, comment))
    return results


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    qf = sys.argv[2] if len(sys.argv) > 2 else None
    run(sys.argv[1], qf)