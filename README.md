# earley-chart-parser

A general context free parser in pure Python. Give it any grammar (left recursive, right recursive, full of ε rules, wildly ambiguous, even cyclic) and it will tell you whether the input belongs to the language, and if so hand you **every** parse, packed into a shared forest that stays polynomial in size even when the number of trees is astronomical.

```text
$ python -m earley grammars/english.grammar "I saw the man with the telescope" --sexpr
7 tokens, 69 chart items, forest 14 nodes / 15 families, 2 parse trees

--- tree 1 ---
(S (NP 'I') (VP (VP (V 'saw') (NP (Det 'the') (N 'man'))) (PP (P 'with') (NP (Det 'the') (N 'telescope')))))

--- tree 2 ---
(S (NP 'I') (VP (V 'saw') (NP (NP (Det 'the') (N 'man')) (PP (P 'with') (NP (Det 'the') (N 'telescope'))))))
```

No dependencies, Python 3.8+.

## Why this exists

Most parsers you meet in practice (recursive descent, LL, LALR, PEG) only accept a restricted slice of grammars. Write `expr -> expr "+" term` for a recursive descent parser and it loops forever; write an ambiguous grammar for yacc and you get conflicts. That is fine for a production compiler, but painful when you are prototyping a language, working with natural language, or just want to find out *what your grammar actually means*.

Earley's algorithm (1970) parses **any** context free grammar. It runs in O(n³) in the worst case, O(n²) for unambiguous grammars and close to linear on the kind of grammars people usually write. This project implements it properly, including the parts textbook versions tend to skip:

* **ε rules done right.** The naive algorithm silently misses parses when a nullable nonterminal completes in the same chart set it was predicted in. This uses the Aycock and Horspool fix (advance over nullable nonterminals at prediction time), and `test_hidden_nullable_trap` in `tests/test_parser.py` pins down the classic failing case.
* **Shared packed parse forest.** Ambiguity is represented, not enumerated. `e -> e "+" e | NUMBER` on 81 tokens has 2.6 × 10²¹ parses; the forest holds them in about 11k packed families and `count()` returns the exact integer in milliseconds.
* **Lazy tree enumeration** when you do want the individual trees, with cycle safe traversal for grammars like `s -> s | "a"` (where `count()` honestly reports `inf`).
* **Useful errors.** A failed parse points at the exact token with line and column, a caret, and the set of terminals that would have been accepted there.
* **A grammar DSL with EBNF sugar** (`?`, `*`, `+`, groups) that desugars into hidden helper rules, which are spliced out of the trees you get back.

## Quick start

```bash
git clone https://github.com/MohammadHossinzehi/earley-chart-parser
cd earley-chart-parser

python -m unittest discover -s tests       # 34 tests, about a second
python examples/calculator.py "2 * (3 + 4) ^ 2 - max(1, 5)"
python examples/benchmark.py
python -m earley grammars/json.grammar '{"a": [1, -2.5, true], "b": null}'
python -m earley grammars/arith.grammar --check
```

Optionally `pip install -e .` gives you an `earley` command that does the same thing as `python -m earley`.

## Using it from Python

```python
from earley import EarleyParser, Transformer

parser = EarleyParser('''
    expr -> expr "+" term | term
    term -> term "*" atom | atom
    atom -> NUMBER | "(" expr ")"
''')

result = parser.parse("2 * (3 + 4)")
print(result.count())          # 1
print(result.tree().pretty())  # indented tree
print(result.tree().sexpr())   # (expr (term (term (atom 2)) '*' (atom '(' ...

class Eval(Transformer):
    def token(self, t):  return int(t.text) if t.kind == "NUMBER" else t.text
    def expr(self, *a):  return a[0] if len(a) == 1 else a[0] + a[2]
    def term(self, *a):  return a[0] if len(a) == 1 else a[0] * a[2]
    def atom(self, *a):  return a[0] if len(a) == 1 else a[1]

print(Eval().transform(result.tree()))   # 14
```

Other entry points: `parser.recognize(text)` for a yes/no answer, `result.trees(limit=10)` to enumerate lazily, `result.forest_size()`, `result.to_dot()` for a Graphviz picture of the forest (`python -m earley g.grammar "..." --dot | dot -Tsvg > forest.svg`). You can also skip the built in lexer and pass a list of `Token(kind, text)` objects straight to `parse`.

## Grammar syntax

```text
# comments start with #
value  -> object | array | STRING | number | "true" | "false" | "null"
number -> "-"? NUMBER
object -> "{" (pair ("," pair)*)? "}"
pair   -> STRING ":" value
array  -> "[" (value ("," value)*)? "]"
```

| Syntax | Meaning |
| --- | --- |
| `name -> a b \| c` | a rule with two alternatives (`::=` and `→` also work, `;` terminators optional) |
| `"x"` or `'x'` | literal terminal, matches a token whose text is `x` |
| `UPPER` (not defined as a rule) | token kind terminal, matches a token whose kind is `UPPER` |
| any name defined on a left side | nonterminal, even if it is upper case like `NP` |
| `ε`, `<empty>`, or an empty alternative | the empty string |
| `x?` `x*` `x+` `( ... )` | EBNF sugar, desugared into helper rules named `_...` |

The first rule's left side is the start symbol unless you pass `start=`. Nonterminals whose names begin with `_` are "hidden": their children are spliced into the parent when trees are built, so `"-"? NUMBER` yields `(number '-' 5)` rather than a tree with a synthetic `_opt` node in the middle. You can use that for your own helper rules too.

The built in lexer does maximal munch over the grammar's literals plus `NUMBER`, `NAME` and `STRING` patterns, skipping whitespace. On a tie a literal wins, which gives normal keyword behaviour: `if` lexes as the keyword, `iffy` as a `NAME`. Pass your own `Lexer(literals, patterns, skip)` if you need something else.

## How it works

```
earley/
  grammar.py   Grammar model, nullable/productive/reachable analysis, DSL parser
  lexer.py     maximal munch tokenizer with line/column tracking
  parser.py    the Earley recogniser and error reporting
  forest.py    forest construction, counting, lazy enumeration, DOT, Transformer
  __main__.py  command line interface
```

**Recognition.** An item is `(rule, dot, origin)`. Chart set *i* holds every item consistent with the first *i* tokens, filled by *predict*, *scan* and *complete* on a worklist. Each set keeps a per nonterminal "waiting" index so completion is a dictionary lookup rather than a scan. While completing, the chart also records which rules finished over which `(symbol, start, end)` span; that index is all the forest builder needs.

**Forest construction.** One `SymbolNode` per `(symbol, start, end)`, each with a list of *families* (a rule and its child nodes). Children are recovered right to left, and every step is validated against the chart: to peel symbol *k* off a rule spanning `[i, pos]`, the item `(rule, k, i)` must exist in the set where that symbol begins. My first version walked left to right and tried every split point; it was correct but went quadratic in memory on long left recursive inputs (it ran out of RAM on a 26k token expression). Anchoring each step on a real chart item made the same input take about 1.4 seconds.

**Counting and enumeration.** Tree counts are a bottom up dynamic program over the forest, done with an explicit stack so deep forests do not hit Python's recursion limit. A node reached again while it is still open lies on a cycle, so it contributes infinity. Enumeration is a lazy generator; a node removes itself from the "active path" set while suspended at `yield` so that sibling subtrees are never wrongly pruned.

## Testing

The suite (`python -m unittest discover -s tests`, also runs under pytest) has four parts:

* **Grammar DSL:** kinds versus nonterminals, ε forms, escapes, EBNF desugaring and sharing, syntax errors, lint warnings.
* **Lexer:** maximal munch, keyword ties, positions across lines, error location.
* **Parser behaviour:** left and right recursion, the hidden nullable trap, Catalan numbers for `e -> e + e` up to k = 8, a 2.6 × 10²¹ tree input that must be counted exactly without being enumerated, PP attachment ambiguity, cyclic grammars, error positions and expected sets, operator precedence and associativity via a `Transformer`, JSON with hidden rules.
* **Differential test against CYK** (`tests/test_against_cyk.py`): 60 random grammars in Chomsky normal form, every string over `{a, b}` up to length 6. An independent CYK implementation counts parse trees and the Earley forest count must match exactly, for accepted and rejected strings alike. This is the test that gives me the most confidence, since CYK is simple enough to be obviously right.

## Performance

From `examples/benchmark.py` on a laptop:

| grammar | tokens | chart items | forest families | time | trees |
| --- | --- | --- | --- | --- | --- |
| arithmetic (unambiguous) | 5,199 | 62,002 | 13,600 | 0.14 s | 1 |
| arithmetic (unambiguous) | 20,799 | 248,002 | 54,400 | 1.1 s | 1 |
| `e -> e + e \| n` | 81 | 2,624 | 11,521 | 0.02 s | 2.6 × 10²¹ |
| `e -> e + e \| n` | 161 | 10,044 | 88,641 | 0.46 s | 1.1 × 10⁴⁵ |

The unambiguous case grows linearly; the ambiguous one grows cubically as theory says, while the number of trees grows exponentially.

## Limitations and next steps

* No Leo optimisation yet, so long *right* recursive chains cost O(n²) instead of O(n). That is the obvious next thing to add.
* Disambiguation is left to you: `tree()` returns the first tree in grammar rule order. Priority or associativity annotations in the DSL would be a nice addition.
* The lexer is deliberately simple (context free, no lexer states). For anything fancy, tokenize yourself and pass `Token` objects in.

## License

MIT
