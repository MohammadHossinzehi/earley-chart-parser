"""A small maximal-munch tokenizer driven by the grammar's literals.

Every literal that appears in the grammar becomes a candidate token whose
kind is the literal text itself. Named patterns (``NUMBER``, ``NAME``, ...)
are tried as well; at each position the longest match wins and, on a tie,
literals beat patterns. That gives the usual keyword behaviour: with the
literal ``"if"`` in the grammar, the input ``if`` lexes as kind ``"if"``
while ``iffy`` still lexes as ``NAME``.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence, Tuple


@dataclass(frozen=True)
class Token:
    kind: str
    text: str
    pos: int = 0
    line: int = 1
    col: int = 1

    def __repr__(self) -> str:
        if self.kind == self.text:
            return "Token(%r)" % self.text
        return "Token(%s, %r)" % (self.kind, self.text)


class LexError(Exception):
    def __init__(self, message: str, pos: int, line: int, col: int):
        super().__init__("%d:%d: %s" % (line, col, message))
        self.pos, self.line, self.col = pos, line, col


DEFAULT_PATTERNS: Tuple[Tuple[str, str], ...] = (
    ("NUMBER", r"\d+(?:\.\d+)?(?:[eE][+-]?\d+)?"),
    ("NAME", r"[A-Za-z_][A-Za-z0-9_]*"),
    ("STRING", r'"(?:[^"\\\n]|\\.)*"'),
)


class Lexer:
    def __init__(
        self,
        literals: Iterable[str] = (),
        patterns: Sequence[Tuple[str, str]] = DEFAULT_PATTERNS,
        skip: Optional[str] = r"\s+",
    ):
        lits = sorted(set(literals), key=lambda s: (-len(s), s))
        self._candidates: List[Tuple[str, "re.Pattern[str]"]] = [(l, re.compile(re.escape(l))) for l in lits]
        self._candidates += [(kind, re.compile(rx)) for kind, rx in patterns]
        self._skip = re.compile(skip) if skip else None

    def tokenize(self, text: str) -> List[Token]:
        tokens: List[Token] = []
        pos, line, line_start = 0, 1, 0
        n = len(text)
        while pos < n:
            if self._skip:
                m = self._skip.match(text, pos)
                if m and m.end() > pos:
                    chunk = m.group()
                    nl = chunk.count("\n")
                    if nl:
                        line += nl
                        line_start = pos + chunk.rfind("\n") + 1
                    pos = m.end()
                    continue
            best_kind, best_end = None, pos
            for kind, rx in self._candidates:
                m = rx.match(text, pos)
                if m and m.end() > best_end:  # strict > keeps the earlier (literal) on ties
                    best_kind, best_end = kind, m.end()
            if best_kind is None:
                raise LexError("unexpected character %r" % text[pos], pos, line, pos - line_start + 1)
            chunk = text[pos:best_end]
            tokens.append(Token(best_kind, chunk, pos, line, pos - line_start + 1))
            nl = chunk.count("\n")
            if nl:
                line += nl
                line_start = pos + chunk.rfind("\n") + 1
            pos = best_end
        return tokens
