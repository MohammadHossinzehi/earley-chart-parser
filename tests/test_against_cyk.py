"""Differential test: Earley vs an independent CYK counter on random CNF grammars.

For a grammar in Chomsky normal form every derivation is a binary tree, so the
number of parse trees CYK counts must equal the Earley forest's tree count
exactly, for every input string, accepted or not.
"""
import itertools
import random
import unittest

from earley import EarleyParser, Grammar, NonTerminal, Rule, Terminal, Token

NTS = ["S", "A", "B", "C"]
TS = ["a", "b"]


def random_cnf(rng):
    rules = []
    for lhs in NTS:
        for _ in range(rng.randint(1, 4)):
            if rng.random() < 0.35:
                rules.append(Rule(lhs, (Terminal(rng.choice(TS)),)))
            else:
                rules.append(Rule(lhs, (NonTerminal(rng.choice(NTS)), NonTerminal(rng.choice(NTS)))))
    rules = list(dict.fromkeys(rules))
    return Grammar(rules, start="S")


def cyk_count(grammar, word):
    n = len(word)
    if n == 0:
        return 0
    table = [[{} for _ in range(n + 1)] for _ in range(n + 1)]
    for i, ch in enumerate(word):
        for r in grammar.rules:
            if len(r.rhs) == 1 and r.rhs[0].value == ch:
                table[i][i + 1][r.lhs] = table[i][i + 1].get(r.lhs, 0) + 1
    for span in range(2, n + 1):
        for i in range(n - span + 1):
            j = i + span
            cell = table[i][j]
            for k in range(i + 1, j):
                for r in grammar.rules:
                    if len(r.rhs) == 2:
                        left = table[i][k].get(r.rhs[0].name, 0)
                        if left:
                            right = table[k][j].get(r.rhs[1].name, 0)
                            if right:
                                cell[r.lhs] = cell.get(r.lhs, 0) + left * right
    return table[0][n].get("S", 0)


class CYKDifferentialTest(unittest.TestCase):
    def test_random_grammars(self):
        rng = random.Random(1234)
        checked = accepted = 0
        for _ in range(60):
            g = random_cnf(rng)
            if "S" not in g.rule_ids:
                continue
            p = EarleyParser(g)
            words = [w for n in range(1, 7) for w in itertools.product(TS, repeat=n)]
            for w in words:
                toks = [Token(c, c) for c in w]
                want = cyk_count(g, w)
                if p.recognize(toks):
                    got = p.parse(toks).count()
                    accepted += 1
                else:
                    got = 0
                self.assertEqual(got, want, "grammar:\n%s\nword: %s" % (g, "".join(w)))
                checked += 1
        self.assertGreater(accepted, 100)  # make sure the test is not vacuous


if __name__ == "__main__":
    unittest.main()
