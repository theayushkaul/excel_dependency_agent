# core/

The deterministic layer. No LLM calls happen anywhere in this folder, and
nothing here should ever need one -- a formula's dependencies are fully
determined by its text, so this is a parsing problem, not a reasoning
problem.

## Files

- **`extractor.py`** -- reads every formula cell in a workbook, tokenizes
  each formula (via `openpyxl.formula.tokenizer`), and resolves every RANGE
  operand -- including named ranges -- to a `(sheet, column)` reference.
  Also flags any cell that calls `INDIRECT(...)`, since part of that cell's
  true target is only known at runtime and can't be recovered by static
  parsing.
- **`graph.py`** -- collapses the cell-level references from `extractor.py`
  into a **column-level** `networkx.DiGraph`. This is the step that turns
  "400 near-identical formulas in a column" into one node with one set of
  outgoing edges -- without it, a large workbook is unreadable as a graph.
  Also detects whether a column is a "stretched pattern" (same formula
  template copied down every row).
- **`tools.py`** -- the `WorkbookContext` class and the handful of
  read-only query methods (`get_precedents`, `get_dependents`,
  `get_column_info`, `find_path`, ...) that both agents call. Every factual
  claim an agent makes should trace back to one of these calls -- if it
  can't, the agent is guessing.

## Edge direction

`graph.add_edge(u, v)` means **u's formulas reference v** -- i.e. u depends
on v. So:

- `successors(u)` = u's precedents (what u depends on)
- `predecessors(v)` = v's dependents (what depends on v)

## What's handled beyond plain cell references

Real workbooks lean on more than `=A1+B1`. All of these resolve to real
column-level edges, not just plain cell/range references:

- **Named ranges** (`AVERAGE(ProductMargins)`)
- **Excel Table structured references** (`SUM(BudgetTable[Q1])`,
  `Table1[@Column]`, `Table1[[Col1]:[Col2]]`, `Table1[#All]`) -- resolved
  via `ws.tables`, mapping each table's header row to its column letters.
  This was the single biggest real-world gap in an earlier version of this
  extractor: structured references don't match a plain `Sheet!$A$1`
  pattern, so a regex that only handles plain addresses silently drops
  every one of them. If a workbook makes heavy use of Tables and a
  dependency tool reports suspiciously few cross-sheet edges, this is the
  first thing to check.
- **3D ranges across multiple sheets** (`SUM(Jan:Mar!B1)`) -- expanded into
  one edge per sheet in the span.
- **Circular references** -- `networkx.DiGraph` holds cycles just fine
  (nothing here requires a DAG), and `WorkbookContext.find_cycles()` /
  `graph.find_cycles()` surfaces them explicitly, the same information
  Excel's own circular-reference warning is based on.

## Known limitations, all surfaced explicitly rather than silently dropped

- **`INDIRECT(...)`** -- `INDIRECT("'"&B2&"'!A:A")` builds its target range
  from a string at runtime. Static tokenization correctly finds `B2` as a
  real precedent (it's a bare reference used to build the string) but
  cannot resolve the dynamic `!A:A` part to any specific sheet -- there's
  no way to know which sheet without evaluating the formula.
  `WorkbookContext.indirect_warnings()` lists every such cell.
- **External workbook references** (`[Book2.xlsx]Sheet1!$A$1`) -- out of
  scope by construction, since the target file isn't being parsed.
  `WorkbookContext.external_ref_warnings()` lists every one, tagged with
  the referenced filename, rather than silently vanishing or being
  misread as a same-workbook reference.
- **Anything else the tokenizer doesn't recognize as an address, a known
  table, or a known named range** lands in
  `WorkbookContext.unresolved_ref_warnings()`. A non-empty list here on a
  real file is a real gap worth investigating -- e.g. a table name typo,
  a defined name pointing at a deleted sheet, or a formula syntax this
  extractor genuinely doesn't handle yet. This list is the thing to check
  first if extraction looks incomplete on a new file; it is not noise to
  suppress. (One thing that looks like it belongs here but doesn't: a bare
  1-3 letter word with no row number, like the `x` in `LET(x, A1+1, x*2)`.
  That can never be a valid standalone Excel reference -- a real
  whole-column reference always has the colon, as in `A:A` -- so it's
  recognized as a LET/LAMBDA local variable name and kept out of this list
  entirely; see `WorkbookContext.local_name_count()`.)

## Where a small model could still genuinely help

Everything above is fixed by better parsing, not by judgment -- the Excel
formula grammar is fully deterministic, so "the parser doesn't handle X
yet" should almost always be answered by extending the parser, not by
asking a model to guess. The one place a model earns its keep is turning
an *unavoidably* unresolvable case into a labeled, best-effort suggestion
that a person can accept or reject -- e.g. "this `INDIRECT` almost
certainly targets `Regions` based on the surrounding formulas" -- and even
then, that suggestion must never be merged into the graph as a verified
edge. If extraction still looks wrong on a real file after checking the
three warning lists above, that's a sign of a genuine remaining parser gap
worth reporting, not a case for a model to paper over.
