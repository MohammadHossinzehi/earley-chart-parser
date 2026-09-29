import unittest

from earley import LexError, Lexer


class LexerTest(unittest.TestCase):
    def test_maximal_munch_on_literals(self):
        lx = Lexer(["<", "<=", "<<="])
        self.assertEqual([t.text for t in lx.tokenize("<<= <= <")], ["<<=", "<=", "<"])

    def test_keywords_beat_names_only_on_ties(self):
        lx = Lexer(["if"])
        toks = lx.tokenize("if iffy")
        self.assertEqual([(t.kind, t.text) for t in toks], [("if", "if"), ("NAME", "iffy")])

    def test_numbers_and_positions(self):
        toks = Lexer(["+"]).tokenize("1.5e3 +\n  42")
        self.assertEqual([(t.kind, t.text, t.line, t.col) for t in toks],
                         [("NUMBER", "1.5e3", 1, 1), ("+", "+", 1, 7), ("NUMBER", "42", 2, 3)])

    def test_unknown_character(self):
        with self.assertRaises(LexError) as cm:
            Lexer().tokenize("abc\n  @")
        self.assertEqual((cm.exception.line, cm.exception.col), (2, 3))

    def test_custom_patterns_and_no_skip(self):
        lx = Lexer([], patterns=[("CH", r".")], skip=None)
        self.assertEqual([t.text for t in lx.tokenize("a b")], ["a", " ", "b"])


if __name__ == "__main__":
    unittest.main()
