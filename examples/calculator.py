"""Evaluate arithmetic with a Transformer, and show what ambiguity does to meaning.

    python examples/calculator.py "2 * (3 + 4) ^ 2 - max(1, 5)"
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from earley import EarleyParser, Grammar, Transformer  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
FUNCS = {"max": max, "min": min, "abs": abs}


class Calc(Transformer):
    def token(self, tok):
        return float(tok.text) if tok.kind == "NUMBER" else tok.text

    def expr(self, *a):
        if len(a) == 1:
            return a[0]
        return a[0] + a[2] if a[1] == "+" else a[0] - a[2]

    def term(self, *a):
        if len(a) == 1:
            return a[0]
        return a[0] * a[2] if a[1] == "*" else a[0] / a[2]

    def power(self, *a):
        return a[0] if len(a) == 1 else a[0] ** a[2]

    def unary(self, *a):
        return a[0] if len(a) == 1 else -a[1]

    def atom(self, *a):
        if len(a) == 1:
            return a[0]
        if a[0] == "(":
            return a[1]
        # NAME "(" args? ")" -- the optional args are spliced in, so a[2:-1] is [] or [list]
        values = a[2] if len(a) == 4 else []
        return FUNCS[a[0]](*values)

    def args(self, *a):
        return [x for x in a if x != ","]


def main():
    with open(os.path.join(HERE, "..", "grammars", "arith.grammar")) as fh:
        parser = EarleyParser(Grammar.from_text(fh.read()))
    src = sys.argv[1] if len(sys.argv) > 1 else "2 * (3 + 4) ^ 2 - max(1, 5)"
    print("%s = %g" % (src, Calc().transform(parser.parse(src).tree())))

    # The same operators written as one flat, ambiguous rule: every tree is a
    # different bracketing, and each bracketing can mean a different number.
    ambiguous = EarleyParser('e -> e "-" e | e "*" e | NUMBER')

    class Flat(Transformer):
        def token(self, tok):
            return float(tok.text) if tok.kind == "NUMBER" else tok.text

        def e(self, *a):
            if len(a) == 1:
                return a[0]
            return a[0] - a[2] if a[1] == "-" else a[0] * a[2]

    src = "8 - 4 - 2 * 3"
    result = ambiguous.parse(src)
    print("\n%r under the flat grammar has %d parses:" % (src, result.count()))
    for tree in result.trees():
        print("  %-40s -> %g" % (tree.sexpr(), Flat().transform(tree)))


if __name__ == "__main__":
    main()
