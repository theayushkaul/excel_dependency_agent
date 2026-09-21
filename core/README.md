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

## Known limitation: INDIRECT

`INDIRECT("'"&B2&"'!A:A")` builds its target range from a string at
runtime. Static tokenization correctly finds `B2` as a real precedent (it's
a bare reference used to build the string) but cannot resolve the dynamic
`!A:A` part to any specific sheet -- there's no way to know which sheet
without evaluating the formula. `WorkbookContext.indirect_warnings()`
surfaces every such cell explicitly rather than silently under-reporting
that column's dependencies. This is the one edge case in
`data/ground_truth.json` tagged `indirect_unresolvable_statically`.
