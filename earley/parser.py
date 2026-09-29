"""Earley recogniser with the Aycock-Horspool nullable fix, plus forest extraction.

An Earley item is ``(rule_index, dot, origin)``: "we are ``dot`` symbols into
rule ``rule_index``, which started at input position ``origin``". Chart set
``i`` holds every item that is consistent with the first ``i`` tokens. Three
operations fill the chart:

* predict  - item waits on nonterminal B at i: add every ``B -> . γ`` at i
* scan     - item waits on a terminal matching token i: advance it into i+1
* complete - item ``A -> γ .`` from origin j: advance everything in set j
             that was waiting on A

The classic trouble spot is ε: an item completing with ``origin == i`` has to
advance waiters in the *same* set, including ones that have not been added
yet. Aycock & Horspool (2002) sidestep it: when predicting a nullable
nonterminal, also advance the predicting item over it immediately. With that
single rule the chart is complete without any fixpoint iteration.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Set, Tuple, Union

from .forest import ParseResult, build_forest, deep_recursion
from .grammar import Grammar, NonTerminal, Terminal
from .lexer import Lexer, Token

Item = Tuple[int, int, int]


class ParseError(Exception):
    """Input is not in the language. ``expected`` lists terminals that would fit."""

    def __init__(self, index: int, token: Optional[Token], expected: Sequence[str]):
        self.index = index
        self.token = token
        self.expected = sorted(set(expected))
        if token is None:
            where, found = "end of input", "end of input"
        else:
            where, found = "%d:%d" % (token.line, token.col), repr(token.text)
        exp = ", ".join(self.expected) if self.expected else "nothing"
        super().__init__("%s: unexpected %s; expected one of: %s" % (where, found, exp))

    def pretty(self, source: str) -> str:
        """Render the error with the offending line and a caret."""
        if self.token is None:
            lines = source.split("\n") or [""]
            line_no, col = len(lines), len(lines[-1]) + 1
        else:
            line_no, col = self.token.line, self.token.col
            lines = source.split("\n")
        text = lines[line_no - 1] if 0 < line_no <= len(lines) else ""
        width = len(self.token.text) if self.token else 1
        return "%s\n  %s\n  %s%s" % (self, text, " " * (col - 1), "^" * max(1, width))


class Chart:
    """The filled Earley chart plus the completion index used to build forests."""

    def __init__(self, n: int):
        self.sets: List[Dict[Item, None]] = [dict() for _ in range(n + 1)]
        # (lhs, origin, end) -> rule indices that completed over that span
        self.completed: Dict[Tuple[str, int, int], List[int]] = {}
        # (lhs, end) -> origins where lhs completed at end
        self.starts: Dict[Tuple[str, int], List[int]] = {}

    @property
    def size(self) -> int:
        return sum(len(s) for s in self.sets)


class EarleyParser:
    """General context-free parser: handles left/right recursion, ε and ambiguity.

    >>> p = EarleyParser(Grammar.from_text('s -> s "+" s | NUMBER'))
    >>> p.parse("1 + 2 + 3").count()
    2
    """

    def __init__(self, grammar: Union[Grammar, str], lexer: Optional[Lexer] = None):
        self.grammar = Grammar.from_text(grammar) if isinstance(grammar, str) else grammar
        self.lexer = lexer or Lexer(self.grammar.literals())

    # -- public API -----------------------------------------------------------
    def tokenize(self, text: str) -> List[Token]:
        return self.lexer.tokenize(text)

    def recognize(self, text_or_tokens: Union[str, Sequence[Token]]) -> bool:
        try:
            self.chart(self._tokens(text_or_tokens))
        except ParseError:
            return False
        return True

    def parse(self, text_or_tokens: Union[str, Sequence[Token]]) -> ParseResult:
        tokens = self._tokens(text_or_tokens)
        chart = self.chart(tokens)
        with deep_recursion(20000 + 12 * len(tokens)):
            root = build_forest(self.grammar, tokens, chart)
        return ParseResult(self.grammar, tokens, root, chart)

    # -- the algorithm ----------------------------------------------------------
    def _tokens(self, x: Union[str, Sequence[Token]]) -> List[Token]:
        return self.tokenize(x) if isinstance(x, str) else list(x)

    def chart(self, tokens: Sequence[Token]) -> Chart:
        g = self.grammar
        rules = g.rules
        rhs_of = [r.rhs for r in rules]
        lhs_of = [r.lhs for r in rules]
        rule_ids = g.rule_ids
        nullable = g.nullable
        n = len(tokens)
        chart = Chart(n)
        sets = chart.sets
        completed, starts = chart.completed, chart.starts
        # waiting[i][B] = items in set i whose next symbol is nonterminal B
        waiting: List[Dict[str, List[Item]]] = []

        for ri in rule_ids[g.start]:
            sets[0][(ri, 0, 0)] = None

        for i in range(n + 1):
            current = sets[i]
            agenda = list(current)
            wait: Dict[str, List[Item]] = {}
            waiting.append(wait)
            predicted: Set[str] = set()
            tok = tokens[i] if i < n else None
            nxt = sets[i + 1] if i < n else None
            k = 0
            while k < len(agenda):
                item = agenda[k]
                k += 1
                ri, dot, origin = item
                rhs = rhs_of[ri]
                if dot == len(rhs):
                    # complete
                    lhs = lhs_of[ri]
                    key = (lhs, origin, i)
                    bucket = completed.get(key)
                    if bucket is None:
                        completed[key] = [ri]
                        starts.setdefault((lhs, i), []).append(origin)
                    elif ri not in bucket:
                        bucket.append(ri)
                    for (pri, pdot, porg) in list(waiting[origin].get(lhs, ())):
                        new = (pri, pdot + 1, porg)
                        if new not in current:
                            current[new] = None
                            agenda.append(new)
                    continue
                sym = rhs[dot]
                if isinstance(sym, NonTerminal):
                    name = sym.name
                    wait.setdefault(name, []).append(item)
                    if name not in predicted:
                        predicted.add(name)
                        for r2 in rule_ids[name]:
                            new = (r2, 0, i)
                            if new not in current:
                                current[new] = None
                                agenda.append(new)
                    if name in nullable:  # Aycock-Horspool
                        new = (ri, dot + 1, origin)
                        if new not in current:
                            current[new] = None
                            agenda.append(new)
                elif tok is not None and sym.matches(tok):
                    nxt[(ri, dot + 1, origin)] = None

            if i < n and not nxt:
                raise ParseError(i, tokens[i], self._expected(current))

        final = completed.get((g.start, 0, n))
        if not final:
            raise ParseError(n, None, self._expected(sets[n]))
        return chart

    def _expected(self, item_set) -> List[str]:
        rules = self.grammar.rules
        out = []
        for ri, dot, _ in item_set:
            rhs = rules[ri].rhs
            if dot < len(rhs) and isinstance(rhs[dot], Terminal):
                out.append(str(rhs[dot]))
        return out
