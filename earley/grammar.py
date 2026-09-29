"""Grammar model and a small EBNF-ish DSL for writing context-free grammars.

Example::

    expr   -> expr ("+" | "-") term | term
    term   -> term ("*" | "/") factor | factor
    factor -> "(" expr ")" | "-" factor | NUMBER

Conventions
  * The left-hand side of the first rule is the start symbol (overridable).
  * ``"..."`` / ``'...'`` are literal terminals, matched against token text.
  * An identifier defined on some left-hand side is a nonterminal. An
    identifier that is never defined and is written in UPPER_CASE is a
    token-kind terminal (``NUMBER``, ``NAME``), matched against token kind.
  * ``ε`` (or ``<empty>``) is the empty string; an empty alternative is
    also allowed: ``opt -> "x" |``.
  * Postfix ``?``, ``*``, ``+`` and parenthesised groups are desugared into
    helper nonterminals whose names start with ``_``. Any nonterminal whose
    name starts with ``_`` is spliced into its parent when trees are built,
    so the sugar does not leak into parse trees.
  * ``#`` starts a comment. Rules may optionally end with ``;``.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, FrozenSet, Iterable, List, Optional, Sequence, Set, Tuple, Union


class GrammarError(Exception):
    """Raised for malformed grammar text or an inconsistent grammar."""


@dataclass(frozen=True)
class Terminal:
    """A terminal symbol.

    ``literal=True`` matches a token whose *text* equals ``value``;
    ``literal=False`` matches a token whose *kind* equals ``value``.
    """

    value: str
    literal: bool = True

    def matches(self, token) -> bool:
        return token.text == self.value if self.literal else token.kind == self.value

    def __str__(self) -> str:
        return '"%s"' % self.value.replace('"', '\\"') if self.literal else self.value


@dataclass(frozen=True)
class NonTerminal:
    name: str

    def __str__(self) -> str:
        return self.name


Symbol = Union[Terminal, NonTerminal]


@dataclass(frozen=True)
class Rule:
    lhs: str
    rhs: Tuple[Symbol, ...]

    def __str__(self) -> str:
        body = " ".join(str(s) for s in self.rhs) or "ε"
        return "%s -> %s" % (self.lhs, body)


class Grammar:
    """An immutable context-free grammar with precomputed nullable set."""

    def __init__(self, rules: Iterable[Rule], start: Optional[str] = None):
        self.rules: List[Rule] = list(rules)
        if not self.rules:
            raise GrammarError("grammar has no rules")
        self.start: str = start or self.rules[0].lhs
        self.rule_ids: Dict[str, List[int]] = {}
        for i, rule in enumerate(self.rules):
            self.rule_ids.setdefault(rule.lhs, []).append(i)
        if self.start not in self.rule_ids:
            raise GrammarError("start symbol '%s' has no rules" % self.start)
        for rule in self.rules:
            for sym in rule.rhs:
                if isinstance(sym, NonTerminal) and sym.name not in self.rule_ids:
                    raise GrammarError("undefined nonterminal '%s' in rule: %s" % (sym.name, rule))
        self.nullable: FrozenSet[str] = self._compute_nullable()

    # -- construction -----------------------------------------------------
    @classmethod
    def from_text(cls, text: str, start: Optional[str] = None) -> "Grammar":
        dsl = _DSLParser(text)
        rules = dsl.parse()
        # helper rules for groups can be emitted before the first user rule,
        # so the default start symbol is the first *written* left-hand side
        return cls(rules, start=start or dsl.first)

    # -- analysis ---------------------------------------------------------
    def _compute_nullable(self) -> FrozenSet[str]:
        nullable: Set[str] = set()
        changed = True
        while changed:
            changed = False
            for rule in self.rules:
                if rule.lhs in nullable:
                    continue
                if all(isinstance(s, NonTerminal) and s.name in nullable for s in rule.rhs):
                    nullable.add(rule.lhs)
                    changed = True
        return frozenset(nullable)

    @property
    def nonterminals(self) -> List[str]:
        return list(self.rule_ids)

    @property
    def terminals(self) -> Set[Terminal]:
        return {s for r in self.rules for s in r.rhs if isinstance(s, Terminal)}

    def literals(self) -> Set[str]:
        return {t.value for t in self.terminals if t.literal}

    def productive(self) -> Set[str]:
        """Nonterminals that derive at least one finite terminal string."""
        prod: Set[str] = set()
        changed = True
        while changed:
            changed = False
            for rule in self.rules:
                if rule.lhs not in prod and all(
                    isinstance(s, Terminal) or s.name in prod for s in rule.rhs
                ):
                    prod.add(rule.lhs)
                    changed = True
        return prod

    def reachable(self) -> Set[str]:
        seen = {self.start}
        stack = [self.start]
        while stack:
            for i in self.rule_ids[stack.pop()]:
                for s in self.rules[i].rhs:
                    if isinstance(s, NonTerminal) and s.name not in seen:
                        seen.add(s.name)
                        stack.append(s.name)
        return seen

    def check(self) -> List[str]:
        """Return human readable warnings (unreachable / unproductive symbols)."""
        warnings = []
        reach, prod = self.reachable(), self.productive()
        for nt in self.nonterminals:
            if nt not in reach:
                warnings.append("nonterminal '%s' is unreachable from '%s'" % (nt, self.start))
            if nt not in prod:
                warnings.append("nonterminal '%s' cannot derive any finite string" % nt)
        return warnings

    def __str__(self) -> str:
        return "\n".join(str(r) for r in self.rules)

    def __len__(self) -> int:
        return len(self.rules)


# ---------------------------------------------------------------------------
# DSL parser
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(
    r"""
    (?P<ws>[ \t\r\n]+|\#[^\n]*)
  | (?P<arrow>->|::=|→)
  | (?P<str>"(?:[^"\\\n]|\\.)*"|'(?:[^'\\\n]|\\.)*')
  | (?P<eps>ε|<empty>)
  | (?P<ident>[A-Za-z_][A-Za-z0-9_]*)
  | (?P<op>[|?*+();])
    """,
    re.VERBOSE,
)

_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "\\": "\\", '"': '"', "'": "'"}
_KIND_RE = re.compile(r"[A-Z][A-Z0-9_]*\Z")

# raw atom forms produced by the DSL parser before name resolution
RawAtom = Tuple[str, str, int]  # (kind: 'id' | 'lit', value, line)


def _unescape(body: str) -> str:
    return re.sub(r"\\(.)", lambda m: _ESCAPES.get(m.group(1), m.group(1)), body)


class _DSLParser:
    def __init__(self, text: str):
        self.toks: List[Tuple[str, str, int]] = []
        pos, line = 0, 1
        while pos < len(text):
            m = _TOKEN_RE.match(text, pos)
            if not m:
                raise GrammarError("line %d: unexpected character %r" % (line, text[pos]))
            kind = m.lastgroup
            val = m.group()
            if kind != "ws":
                if kind == "str":
                    val = _unescape(val[1:-1])
                    if val == "":
                        raise GrammarError("line %d: empty literal \"\" (use ε instead)" % line)
                self.toks.append((kind, val, line))
            line += val.count("\n") if kind == "ws" else 0
            pos = m.end()
        self.i = 0
        self.raw: List[Tuple[str, List[RawAtom]]] = []
        self.generated: Dict[tuple, str] = {}
        self.counter = 0
        self.first: Optional[str] = None

    # -- token helpers ------------------------------------------------------
    def peek(self, k: int = 0):
        j = self.i + k
        return self.toks[j] if j < len(self.toks) else ("eof", "", self.toks[-1][2] if self.toks else 1)

    def next(self):
        tok = self.peek()
        self.i += 1
        return tok

    def expect(self, kind: str, value: Optional[str] = None):
        tok = self.next()
        if tok[0] != kind or (value is not None and tok[1] != value):
            want = value or kind
            raise GrammarError("line %d: expected %s, found %r" % (tok[2], want, tok[1] or "end of input"))
        return tok

    def at_rule_start(self) -> bool:
        return self.peek()[0] == "ident" and self.peek(1)[0] == "arrow"

    # -- grammar ------------------------------------------------------------
    def parse(self) -> List[Rule]:
        while self.peek()[0] != "eof":
            name = self.expect("ident")[1]
            self.expect("arrow")
            if self.first is None:
                self.first = name
            for seq in self.alternatives():
                self.raw.append((name, seq))
            if self.peek()[:2] == ("op", ";"):
                self.next()
        if not self.raw:
            raise GrammarError("grammar has no rules")
        return self.resolve()

    def alternatives(self) -> List[List[RawAtom]]:
        alts = [self.sequence()]
        while self.peek()[:2] == ("op", "|"):
            self.next()
            alts.append(self.sequence())
        return alts

    def sequence(self) -> List[RawAtom]:
        seq: List[RawAtom] = []
        while True:
            kind, val, line = self.peek()
            if kind == "eof" or (kind == "op" and val in "|;)") or self.at_rule_start():
                return seq
            seq.extend(self.item())

    def item(self) -> List[RawAtom]:
        atom = self.atom()
        while self.peek()[0] == "op" and self.peek()[1] in "?*+":
            op = self.next()[1]
            if atom is None:
                raise GrammarError("line %d: '%s' applied to ε" % (self.peek()[2], op))
            atom = self.repeat(atom, op)
        return [] if atom is None else [atom]

    def atom(self) -> Optional[RawAtom]:
        kind, val, line = self.next()
        if kind == "ident":
            return ("id", val, line)
        if kind == "str":
            return ("lit", val, line)
        if kind == "eps":
            return None
        if kind == "op" and val == "(":
            alts = self.alternatives()
            self.expect("op", ")")
            key = ("group", tuple(tuple(a[:2] for a in alt) for alt in alts))
            name = self.generated.get(key)
            if name is None:
                self.counter += 1
                name = self.generated[key] = "_g%d" % self.counter
                for alt in alts:
                    self.raw.append((name, alt))
            return ("id", name, line)
        raise GrammarError("line %d: unexpected %r" % (line, val or "end of input"))

    def repeat(self, atom: RawAtom, op: str) -> RawAtom:
        key = (op, atom[:2])
        name = self.generated.get(key)
        if name is None:
            suffix = {"?": "opt", "*": "star", "+": "plus"}[op]
            if atom[0] == "id":
                base = atom[1].lstrip("_")
            else:
                self.counter += 1
                base = "lit%d" % self.counter
            name = self.generated[key] = "_%s_%s" % (base, suffix)
            me = ("id", name, atom[2])
            if op == "?":
                self.raw += [(name, [atom]), (name, [])]
            elif op == "*":  # left recursion is cheap for Earley
                self.raw += [(name, [me, atom]), (name, [])]
            else:
                self.raw += [(name, [me, atom]), (name, [atom])]
        return ("id", name, atom[2])

    def resolve(self) -> List[Rule]:
        defined = {lhs for lhs, _ in self.raw}
        rules = []
        for lhs, seq in self.raw:
            rhs: List[Symbol] = []
            for kind, val, line in seq:
                if kind == "lit":
                    rhs.append(Terminal(val, literal=True))
                elif val in defined:
                    rhs.append(NonTerminal(val))
                elif _KIND_RE.match(val):
                    rhs.append(Terminal(val, literal=False))
                else:
                    raise GrammarError(
                        "line %d: undefined nonterminal '%s' (token kinds must be UPPER_CASE)" % (line, val)
                    )
            rules.append(Rule(lhs, tuple(rhs)))
        return rules
