import unittest

from earley import Grammar, GrammarError, NonTerminal, Terminal


class GrammarDSLTest(unittest.TestCase):
    def test_basic_rules_and_start(self):
        g = Grammar.from_text('s -> "a" s | "b"')
        self.assertEqual(g.start, "s")
        self.assertEqual([str(r) for r in g.rules], ['s -> "a" s', 's -> "b"'])

    def test_kind_terminals_vs_nonterminals(self):
        g = Grammar.from_text("S -> NP NUMBER\nNP -> NAME")
        rhs = g.rules[0].rhs
        self.assertEqual(rhs[0], NonTerminal("NP"))  # defined, so a nonterminal even though upper case
        self.assertEqual(rhs[1], Terminal("NUMBER", literal=False))

    def test_undefined_lowercase_is_an_error(self):
        with self.assertRaises(GrammarError) as cm:
            Grammar.from_text("s -> thing")
        self.assertIn("thing", str(cm.exception))

    def test_epsilon_forms_and_nullable(self):
        g = Grammar.from_text("a -> b c\nb -> ε | 'x'\nc -> <empty>\nd -> 'y' |\n")
        self.assertEqual(g.nullable, frozenset({"a", "b", "c", "d"}))

    def test_comments_semicolons_and_alternate_arrows(self):
        g = Grammar.from_text("# header\ns ::= 'a' ;  # trailing\nt → 'b';")
        self.assertEqual(len(g), 2)

    def test_escapes_in_literals(self):
        g = Grammar.from_text(r's -> "\"" "\\" "\n"')
        self.assertEqual([t.value for t in g.rules[0].rhs], ['"', "\\", "\n"])

    def test_ebnf_sugar_desugars_to_hidden_rules(self):
        g = Grammar.from_text('list -> "[" (item ("," item)*)? "]"\nitem -> NUMBER')
        self.assertEqual(g.start, "list")
        hidden = [nt for nt in g.nonterminals if nt.startswith("_")]
        self.assertTrue(hidden)
        self.assertIn(g.start, g.nonterminals)

    def test_repeated_sugar_is_shared(self):
        g = Grammar.from_text("s -> x* 'a' x*\nx -> 'x'")
        self.assertEqual(sum(1 for nt in g.nonterminals if nt == "_x_star"), 1)
        self.assertEqual(len(g.rule_ids["_x_star"]), 2)

    def test_plus_and_opt(self):
        g = Grammar.from_text("s -> 'a'+ 'b'?")
        self.assertNotIn("s", g.nullable)
        g2 = Grammar.from_text("s -> 'a'* 'b'?")
        self.assertIn("s", g2.nullable)

    def test_explicit_start(self):
        g = Grammar.from_text("a -> 'x'\nb -> a a", start="b")
        self.assertEqual(g.start, "b")
        with self.assertRaises(GrammarError):
            Grammar.from_text("a -> 'x'", start="zzz")

    def test_syntax_errors(self):
        for bad in ["-> 'a'", "s -> 'a' )", "s -> ('a'", "s -> $", 's -> ""', "s -> ε*"]:
            with self.subTest(bad=bad), self.assertRaises(GrammarError):
                Grammar.from_text(bad)

    def test_check_reports_unreachable_and_unproductive(self):
        g = Grammar.from_text("s -> 'a'\norphan -> 'b'\nloop -> loop 'c'\nt -> loop")
        warnings = "\n".join(g.check())
        self.assertIn("'orphan' is unreachable", warnings)
        self.assertIn("'loop' cannot derive", warnings)
        self.assertEqual(Grammar.from_text("s -> 'a' s | 'a'").check(), [])


if __name__ == "__main__":
    unittest.main()
