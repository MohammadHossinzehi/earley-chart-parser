"""Command line front end.

    python -m earley GRAMMAR_FILE "input text"      # parse and print trees
    echo "1 + 2" | python -m earley GRAMMAR_FILE    # input from stdin
    python -m earley GRAMMAR_FILE --check           # lint the grammar only
    python -m earley GRAMMAR_FILE "..." --dot > f.dot
"""
from __future__ import annotations

import argparse
import sys

from . import EarleyParser, Grammar, GrammarError, LexError, ParseError


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m earley", description="Parse text with any context-free grammar.")
    ap.add_argument("grammar", help="grammar file")
    ap.add_argument("input", nargs="?", help="text to parse (default: stdin)")
    ap.add_argument("--start", help="start symbol (default: first rule)")
    ap.add_argument("--limit", type=int, default=5, help="max trees to print (default 5, 0 = all)")
    ap.add_argument("--sexpr", action="store_true", help="print trees as s-expressions")
    ap.add_argument("--dot", action="store_true", help="print the shared forest as Graphviz DOT")
    ap.add_argument("--check", action="store_true", help="only load and lint the grammar")
    args = ap.parse_args(argv)

    try:
        with open(args.grammar, encoding="utf-8") as fh:
            grammar = Grammar.from_text(fh.read(), start=args.start)
    except (OSError, GrammarError) as exc:
        print("grammar error: %s" % exc, file=sys.stderr)
        return 2

    if args.check:
        print("%d rules, start symbol '%s', nullable: %s" % (
            len(grammar), grammar.start, ", ".join(sorted(grammar.nullable)) or "none"))
        for w in grammar.check():
            print("warning: " + w)
        return 0

    text = args.input if args.input is not None else sys.stdin.read()
    parser = EarleyParser(grammar)
    try:
        result = parser.parse(text)
    except LexError as exc:
        print("lex error: %s" % exc, file=sys.stderr)
        return 1
    except ParseError as exc:
        print("parse error: " + exc.pretty(text), file=sys.stderr)
        return 1

    if args.dot:
        print(result.to_dot())
        return 0

    count = result.count()
    nodes, families = result.forest_size()
    print("%d tokens, %d chart items, forest %d nodes / %d families, %s parse tree%s" % (
        len(result.tokens), result.chart.size, nodes, families,
        "infinitely many" if count == float("inf") else count, "" if count == 1 else "s"))
    limit = None if args.limit == 0 else args.limit
    for i, tree in enumerate(result.trees(limit)):
        print("\n--- tree %d ---" % (i + 1))
        print(tree.sexpr() if args.sexpr else tree.pretty())
    return 0


if __name__ == "__main__":
    sys.exit(main())
