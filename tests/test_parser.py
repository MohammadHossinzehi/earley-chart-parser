import math
import os
import unittest

from earley import EarleyParser, Grammar, LexError, ParseError, Token, Transformer

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")


def load(name):
    with open(os.path.join(ROOT, "grammars", name), encoding="utf-8") as fh:
        return EarleyParser(Grammar.from_text(fh.read()))


def catalan(n):
    return math.comb(2 * n, n) // (n + 1)


class RecognitionTest(unittest.TestCase):
    def test_left_and_right_recursion(self):
        left = EarleyParser("s -> s 'a' | 'a'")
        right = EarleyParser("s -> 'a' s | 'a'")
        for n in (1, 2, 50):
            self.assertEqual(left.parse("a " * n).count(), 1)
            self.assertEqual(right.parse("a " * n).count(), 1)
        self.assertFalse(left.recognize(""))

    def test_empty_input_with_nullable_start(self):
        p = EarleyParser("s -> ε | '(' s ')' s")
        self.assertTrue(p.recognize(""))
        self.assertTrue(p.recognize("(()())()"))
        self.assertFalse(p.recognize("(()"))

    def test_hidden_nullable_trap(self):
        # The grammar that breaks naive Earley: a completion at the same
        # position must reach items added *after* it.
        p = EarleyParser("s -> a a a a\na -> 'x' | e\ne -> ε")
        for n in range(5):
            self.assertTrue(p.recognize("x " * n), n)
        self.assertFalse(p.recognize("x x x x x"))
        # x placed in any one of the four slots
        self.assertEqual(p.parse("x").count(), 4)

    def test_catalan_ambiguity(self):
        p = EarleyParser('e -> e "+" e | NUMBER')
        for k in range(1, 9):
            src = " + ".join(["1"] * (k + 1))
            self.assertEqual(p.parse(src).count(), catalan(k), k)

    def test_huge_ambiguity_is_counted_not_enumerated(self):
        p = EarleyParser('e -> e "+" e | NUMBER')
        r = p.parse(" + ".join(["1"] * 41))  # Catalan(40) ~ 2.6e21 trees
        self.assertEqual(r.count(), catalan(40))
        nodes, families = r.forest_size()
        self.assertLess(families, 20000)  # the shared forest stays polynomial
        self.assertEqual(len(list(r.trees(limit=3))), 3)

    def test_pp_attachment(self):
        p = load("english.grammar")
        self.assertEqual(p.parse("I saw the man with the telescope").count(), 2)
        # 3 PPs: Catalan-style blow-up
        self.assertEqual(p.parse("I saw the man on the hill with the telescope").count(), 5)
        self.assertFalse(p.recognize("I saw the"))

    def test_cyclic_grammar(self):
        p = EarleyParser("s -> s | 'a'")
        r = p.parse("a")
        self.assertEqual(r.count(), math.inf)
        self.assertEqual([t.sexpr() for t in r.trees()], ["(s 'a')"])

    def test_parse_tokens_directly(self):
        p = EarleyParser("s -> WORD+")
        toks = [Token("WORD", w) for w in ["x", "y", "z"]]
        tree = p.parse(toks).tree()
        self.assertEqual(tree.text(), "x y z")
        self.assertEqual(len(tree.children), 3)  # _WORD_plus spliced away


class ErrorTest(unittest.TestCase):
    def test_error_position_and_expected(self):
        p = load("arith.grammar")
        with self.assertRaises(ParseError) as cm:
            p.parse("1 + (2 * )")
        e = cm.exception
        self.assertEqual((e.token.text, e.token.col), (")", 10))
        self.assertEqual(e.expected, ['"("', '"-"', "NAME", "NUMBER"])
        self.assertIn("^", e.pretty("1 + (2 * )"))

    def test_unexpected_end(self):
        p = load("arith.grammar")
        with self.assertRaises(ParseError) as cm:
            p.parse("(1 + 2")
        self.assertIsNone(cm.exception.token)
        self.assertIn('")"', cm.exception.expected)

    def test_lex_error_propagates(self):
        with self.assertRaises(LexError):
            load("arith.grammar").parse("1 $ 2")


class TreeTest(unittest.TestCase):
    def test_precedence_shape(self):
        tree = load("arith.grammar").parse("1 + 2 * 3").tree()
        self.assertEqual(
            tree.sexpr(),
            "(expr (expr (term (power (unary (atom 1))))) '+' "
            "(term (term (power (unary (atom 2)))) '*' (power (unary (atom 3)))))",
        )

    def test_transformer_evaluates(self):
        class Calc(Transformer):
            def token(self, t):
                return int(t.text) if t.kind == "NUMBER" else t.text

            def expr(self, *a):
                return a[0] if len(a) == 1 else (a[0] + a[2] if a[1] == "+" else a[0] - a[2])

            def term(self, *a):
                return a[0] if len(a) == 1 else (a[0] * a[2] if a[1] == "*" else a[0] // a[2])

            def power(self, *a):
                return a[0] if len(a) == 1 else a[0] ** a[2]

            def unary(self, *a):
                return a[0] if len(a) == 1 else -a[1]

            def atom(self, *a):
                return a[0] if len(a) == 1 else a[1]

        p = load("arith.grammar")
        for src, want in [("1 + 2 * 3", 7), ("(1 + 2) * 3", 9), ("2 ^ 3 ^ 2", 512),
                          ("10 - 4 - 3", 3), ("-2 ^ 2", 4), ("100 / 7 / 2", 7)]:
            self.assertEqual(Calc().transform(p.parse(src).tree()), want, src)

    def test_json_and_hidden_rules(self):
        p = load("json.grammar")
        tree = p.parse('{"k": [1, 2, 3], "e": []}').tree()
        labels = set()

        def walk(t):
            if hasattr(t, "label"):
                labels.add(t.label)
                for c in t.children:
                    walk(c)

        walk(tree)
        self.assertFalse(any(l.startswith("_") for l in labels), labels)
        self.assertEqual(p.parse("[[[]]]").count(), 1)
        self.assertFalse(p.recognize("[1,]"))

    def test_dot_output(self):
        dot = EarleyParser('e -> e "+" e | NUMBER').parse("1 + 2 + 3").to_dot()
        self.assertTrue(dot.startswith("digraph forest {"))
        self.assertIn("shape=point", dot)  # packed node for the ambiguity
        self.assertTrue(dot.rstrip().endswith("}"))

    def test_trees_are_distinct(self):
        r = EarleyParser('e -> e "+" e | NUMBER').parse("1 + 2 + 3 + 4 + 5")
        trees = list(r.trees())
        self.assertEqual(len(trees), 14)
        self.assertEqual(len(set(trees)), 14)


if __name__ == "__main__":
    unittest.main()
