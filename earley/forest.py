"""Shared packed parse forests, tree enumeration and tree utilities.

An ambiguous grammar can give a sentence exponentially many parse trees
(``E -> E "+" E`` gives Catalan(k) trees for k operators), so we never build
them eagerly. Instead the chart is turned into a *forest*: one
:class:`SymbolNode` per ``(nonterminal, start, end)`` span, each holding a
list of *families* (rule + child nodes). Shared sub-spans are shared nodes,
so the forest stays polynomial even when the tree count explodes. Trees are
then counted by dynamic programming or enumerated lazily on demand.

Cyclic grammars (``S -> S | "a"``) produce forests with cycles and
infinitely many trees; :meth:`ParseResult.count` returns ``math.inf`` and
enumeration yields only the finite, cycle-free trees.
"""
from __future__ import annotations

import math
import sys
from contextlib import contextmanager
from typing import Dict, Iterator, List, Optional, Sequence, Tuple, Union

from .grammar import Grammar, NonTerminal, Rule, Terminal
from .lexer import Token


@contextmanager
def deep_recursion(depth: int):
    """Temporarily raise the recursion limit for depth-first forest walks."""
    old = sys.getrecursionlimit()
    if depth > old:
        sys.setrecursionlimit(depth)
    try:
        yield
    finally:
        sys.setrecursionlimit(old)


class SymbolNode:
    __slots__ = ("symbol", "start", "end", "families")

    def __init__(self, symbol: str, start: int, end: int):
        self.symbol = symbol
        self.start = start
        self.end = end
        self.families: List[Tuple[Rule, Tuple["Node", ...]]] = []

    def __repr__(self) -> str:
        return "SymbolNode(%s, %d, %d, %d families)" % (self.symbol, self.start, self.end, len(self.families))


class TokenNode:
    __slots__ = ("token", "index")

    def __init__(self, token: Token, index: int):
        self.token = token
        self.index = index

    def __repr__(self) -> str:
        return "TokenNode(%r)" % self.token.text


Node = Union[SymbolNode, TokenNode]


def build_forest(grammar: Grammar, tokens: Sequence[Token], chart) -> SymbolNode:
    """Turn a finished chart into a shared packed parse forest.

    Children are recovered right to left and every step is checked against
    the chart: to peel symbol ``k-1`` off ``rule -> α . β`` spanning
    ``[i, pos]`` we need the item ``(rule, k-1, i)`` in the set where that
    symbol starts. That keeps the work proportional to the chart rather than
    to every conceivable split point.
    """
    rules = grammar.rules
    sets = chart.sets
    completed, starts = chart.completed, chart.starts
    nodes: Dict[Tuple[str, int, int], SymbolNode] = {}
    leaves: Dict[int, TokenNode] = {}
    split_memo: Dict[Tuple[int, int, int, int], List[Tuple[Node, ...]]] = {}

    def leaf(i: int) -> TokenNode:
        t = leaves.get(i)
        if t is None:
            t = leaves[i] = TokenNode(tokens[i], i)
        return t

    def node(sym: str, i: int, j: int) -> SymbolNode:
        key = (sym, i, j)
        nd = nodes.get(key)
        if nd is not None:
            return nd
        nd = nodes[key] = SymbolNode(sym, i, j)  # registered first: cycles become back edges
        for ri in completed.get(key, ()):
            for children in splits(ri, len(rules[ri].rhs), i, j):
                nd.families.append((rules[ri], children))
        return nd

    def splits(ri: int, k: int, i: int, pos: int) -> List[Tuple[Node, ...]]:
        """All ways rhs[:k] of rule ri derives tokens[i:pos]."""
        key = (ri, k, i, pos)
        res = split_memo.get(key)
        if res is not None:
            return res
        res = []
        if k == 0:
            if i == pos:
                res.append(())
        else:
            sym = rules[ri].rhs[k - 1]
            prev_item = (ri, k - 1, i)
            if isinstance(sym, Terminal):
                s = pos - 1
                if s >= i and prev_item in sets[s] and sym.matches(tokens[s]):
                    lf = leaf(s)
                    res = [r + (lf,) for r in splits(ri, k - 1, i, s)]
            else:
                for s in starts.get((sym.name, pos), ()):
                    if s >= i and prev_item in sets[s]:
                        rests = splits(ri, k - 1, i, s)
                        if rests:
                            child = node(sym.name, s, pos)
                            res.extend(r + (child,) for r in rests)
        split_memo[key] = res
        return res

    return node(grammar.start, 0, len(tokens))


# ---------------------------------------------------------------------------
# Trees
# ---------------------------------------------------------------------------


class Tree:
    """A concrete parse tree. Leaves are :class:`Token` objects."""

    __slots__ = ("label", "children", "rule")

    def __init__(self, label: str, children: List[Union["Tree", Token]], rule: Optional[Rule] = None):
        self.label = label
        self.children = children
        self.rule = rule

    def __eq__(self, other) -> bool:
        return isinstance(other, Tree) and self.sexpr() == other.sexpr()

    def __hash__(self) -> int:
        return hash(self.sexpr())

    def __repr__(self) -> str:
        return "Tree(%s)" % self.sexpr()

    def tokens(self) -> List[Token]:
        out: List[Token] = []
        stack: List[Union[Tree, Token]] = [self]
        while stack:
            x = stack.pop()
            if isinstance(x, Tree):
                stack.extend(reversed(x.children))
            else:
                out.append(x)
        return out

    def text(self, sep: str = " ") -> str:
        return sep.join(t.text for t in self.tokens())

    def sexpr(self) -> str:
        parts = [self.label]
        for c in self.children:
            parts.append(c.sexpr() if isinstance(c, Tree) else repr(c.text) if c.kind == c.text else c.text)
        return "(" + " ".join(parts) + ")"

    def pretty(self, indent: str = "  ") -> str:
        lines: List[str] = []

        def walk(t: Union[Tree, Token], depth: int) -> None:
            pad = indent * depth
            if isinstance(t, Tree):
                lines.append(pad + t.label)
                for c in t.children:
                    walk(c, depth + 1)
            else:
                lines.append(pad + (repr(t.text) if t.kind == t.text else "%s %r" % (t.kind, t.text)))

        walk(self, 0)
        return "\n".join(lines)


def _is_hidden(label: str) -> bool:
    return label.startswith("_")


def iter_trees(root: SymbolNode) -> Iterator[Tree]:
    """Lazily yield every cycle-free tree in the forest (hidden rules spliced in)."""

    # ``path`` holds the nodes on the active derivation chain; a node removes
    # itself while suspended at ``yield`` so siblings never see it.
    path: set = set()

    def trees(nd: Node) -> Iterator[Union[Tree, Token]]:
        if isinstance(nd, TokenNode):
            yield nd.token
            return
        if nd in path:
            return
        path.add(nd)
        for rule, children in nd.families:
            for combo in product(children):
                kids: List[Union[Tree, Token]] = []
                for c in combo:
                    if isinstance(c, Tree) and _is_hidden(c.label):
                        kids.extend(c.children)
                    else:
                        kids.append(c)
                path.discard(nd)
                yield Tree(nd.symbol, kids, rule)
                path.add(nd)
        path.discard(nd)

    def product(children: Tuple[Node, ...]) -> Iterator[tuple]:
        if not children:
            yield ()
            return
        for first in trees(children[0]):
            for rest in product(children[1:]):
                yield (first,) + rest

    for t in trees(root):
        yield t  # type: ignore[misc]


def count_trees(root: SymbolNode) -> Union[int, float]:
    """Count trees bottom-up with an explicit stack (forests can be very deep).

    A child that is still "open" when we reach it again lies on the current
    DFS path, i.e. the forest has a cycle through it: every tree above it can
    be pumped forever, so it contributes ``math.inf``.
    """
    memo: Dict[int, Union[int, float]] = {}
    open_: set = set()
    stack: List[Tuple[SymbolNode, bool]] = [(root, False)]
    while stack:
        nd, finished = stack.pop()
        key = id(nd)
        if finished:
            total: Union[int, float] = 0
            for _, children in nd.families:
                prod: Union[int, float] = 1
                for c in children:
                    if not isinstance(c, TokenNode):
                        prod *= memo.get(id(c), math.inf)
                total += prod
            memo[key] = total
            open_.discard(key)
            continue
        if key in memo or key in open_:
            continue
        open_.add(key)
        stack.append((nd, True))
        for _, children in nd.families:
            for c in children:
                if isinstance(c, SymbolNode) and id(c) not in memo and id(c) not in open_:
                    stack.append((c, False))
    return memo[id(root)]


def forest_nodes(root: SymbolNode) -> List[SymbolNode]:
    seen: Dict[int, SymbolNode] = {}
    stack: List[Node] = [root]
    while stack:
        nd = stack.pop()
        if isinstance(nd, TokenNode) or id(nd) in seen:
            continue
        seen[id(nd)] = nd
        for _, children in nd.families:
            stack.extend(children)
    return list(seen.values())


def to_dot(root: SymbolNode) -> str:
    """Graphviz rendering: boxes are symbol nodes, dots are packed families."""
    out = ["digraph forest {", "  rankdir=TB;", '  node [fontname="Helvetica"];']
    ids: Dict[int, str] = {}

    def nid(x) -> str:
        if id(x) not in ids:
            ids[id(x)] = "n%d" % len(ids)
        return ids[id(x)]

    def esc(s: str) -> str:
        return s.replace("\\", "\\\\").replace('"', '\\"')

    tokens_seen = set()
    for nd in forest_nodes(root):
        out.append('  %s [shape=box, label="%s %d..%d"];' % (nid(nd), esc(nd.symbol), nd.start, nd.end))
        many = len(nd.families) > 1
        for fi, (rule, children) in enumerate(nd.families):
            src = nid(nd)
            if many:
                pk = "%s_p%d" % (nid(nd), fi)
                out.append('  %s [shape=point, xlabel="%s"];' % (pk, esc(str(rule))))
                out.append("  %s -> %s;" % (src, pk))
                src = pk
            for c in children:
                if isinstance(c, TokenNode) and id(c) not in tokens_seen:
                    tokens_seen.add(id(c))
                    out.append('  %s [shape=ellipse, label="%s"];' % (nid(c), esc(c.token.text)))
                out.append("  %s -> %s;" % (src, nid(c)))
    out.append("}")
    return "\n".join(out)


class ParseResult:
    def __init__(self, grammar: Grammar, tokens: List[Token], root: SymbolNode, chart):
        self.grammar = grammar
        self.tokens = tokens
        self.root = root
        self.chart = chart

    def count(self) -> Union[int, float]:
        """Number of distinct parse trees (``math.inf`` for cyclic derivations)."""
        return count_trees(self.root)

    @property
    def ambiguous(self) -> bool:
        return self.count() > 1

    def _depth(self) -> int:
        return 20000 + 12 * len(self.tokens)

    def trees(self, limit: Optional[int] = None) -> Iterator[Tree]:
        """Lazily enumerate trees (optionally at most ``limit`` of them)."""
        it = iter_trees(self.root)
        produced = 0
        while limit is None or produced < limit:
            with deep_recursion(self._depth()):
                t = next(it, None)
            if t is None:
                return
            produced += 1
            yield t

    def tree(self) -> Tree:
        """The first tree (deterministic: follows rule order in the grammar)."""
        for t in self.trees(1):
            return t
        raise ValueError("forest has no finite tree")

    def to_dot(self) -> str:
        return to_dot(self.root)

    def forest_size(self) -> Tuple[int, int]:
        """(symbol nodes, packed families) in the shared forest."""
        nodes = forest_nodes(self.root)
        return len(nodes), sum(len(n.families) for n in nodes)


class Transformer:
    """Bottom-up tree evaluator. Define a method per nonterminal name.

    Each method receives the already-transformed children as positional
    arguments. Tokens are passed through :meth:`token` (default: the text).
    """

    def transform(self, tree: Union[Tree, Token]):
        if isinstance(tree, Token):
            return self.token(tree)
        args = [self.transform(c) for c in tree.children]
        fn = getattr(self, tree.label, None)
        if fn is None:
            return self.default(tree.label, args)
        return fn(*args)

    def token(self, tok: Token):
        return tok.text

    def default(self, label: str, args: list):
        return args[0] if len(args) == 1 else (label, args)
