"""Rough scaling check: chart size and wall time as the input grows.

    python examples/benchmark.py

Earley is O(n^3) in general, O(n^2) for unambiguous grammars and O(n) for
most LR-like grammars in practice. The arithmetic grammar below should grow
roughly linearly; the ambiguous one grows cubically (while its tree count
grows exponentially, which is why the forest matters).
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from earley import EarleyParser, Grammar  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))


def timed(parser, src):
    t0 = time.perf_counter()
    result = parser.parse(src)
    count = result.count()
    return time.perf_counter() - t0, result, count


def main():
    with open(os.path.join(HERE, "..", "grammars", "arith.grammar")) as fh:
        arith = EarleyParser(Grammar.from_text(fh.read()))
    print("unambiguous arithmetic (left recursive, with calls and parens)")
    print("%8s %10s %10s %8s" % ("tokens", "items", "families", "seconds"))
    for reps in (100, 400, 1600):
        src = " + ".join(["(1 * 2 - max(3, 4))"] * reps)
        secs, result, _ = timed(arith, src)
        print("%8d %10d %10d %8.2f" % (len(result.tokens), result.chart.size, result.forest_size()[1], secs))

    ambiguous = EarleyParser('e -> e "+" e | NUMBER')
    print("\nfully ambiguous e -> e + e | n")
    print("%8s %10s %10s %8s  %s" % ("tokens", "items", "families", "seconds", "trees"))
    for k in (10, 40, 80):
        secs, result, count = timed(ambiguous, " + ".join(["1"] * (k + 1)))
        print("%8d %10d %10d %8.2f  %.3e" % (len(result.tokens), result.chart.size, result.forest_size()[1], secs, count))


if __name__ == "__main__":
    main()
