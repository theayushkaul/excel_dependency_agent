# excel-dependency-agent

A baseline for making a large, multi-sheet Excel workbook's formula
relationships understandable -- deterministically extracted, with two
agent modes on top for exploring and documenting it.

## The core idea

A formula's dependencies are fully determined by its text. So the graph
itself is built by parsing, never by an LLM guessing -- that part has to
be exactly right, and it's cheap to make exactly right. The two agents
built on top only *narrate* what the deterministic layer already knows;
neither is allowed to invent a dependency the graph doesn't contain.

```
Excel workbook
      |
      v
Deterministic extraction core   (core/)
   parse -> graph -> query tools
      |                    \
      v                     \  live queries
Deep agent                    ReAct agent
(full doc pass,                (per-question,
 offline)                       interactive)
      |                       /
      v                     /
Documentation store  <-----      (fast-path cache;
(agents/memory.py)                 never authoritative)
```

## Layout

```
core/               deterministic layer -- extraction, graph, query tools (no LLM, no key needed)
agents/             deep agent (batch docs) + ReAct agent (Q&A), sharing core/'s tools
data/                the synthetic benchmark workbook + its ground truth
validate.py          scores extraction precision/recall/F1 against ground truth
walkthrough.ipynb    runs all of the above end to end, with explanations
```

Each subfolder has its own README with more detail.

## Setup

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-...   # only needed for agents/, not for core/ or validate.py
```

## Quickstart

```bash
# 1. Deterministic extraction + accuracy check -- no API key needed
python validate.py

# 2. Explore interactively (needs ANTHROPIC_API_KEY)
python -c "
from core.tools import WorkbookContext
from agents import DocStore, ReActAgent

ctx = WorkbookContext('data/dependency_benchmark.xlsx')
agent = ReActAgent(ctx, DocStore('data/doc_store.json'))
print(agent.ask('What does Sales.Total ultimately depend on, and is any of it dynamic?'))
"
```

Or just open `walkthrough.ipynb`, which does all of the above with
explanations in between.

## What's included / what's a deliberate stub

This is a **baseline**, not a finished product. Included:

- Full deterministic extraction: formulas, cross-sheet refs, named ranges,
  **Excel Table structured references**, **3D sheet ranges**, stretched-
  pattern detection, **circular-reference detection**, and explicit (never
  silent) flagging of `INDIRECT`, external-workbook references, and
  anything else the parser can't resolve
- Two verified benchmark workbooks: `data/dependency_benchmark.xlsx` (the
  main one, with hand-checked `ground_truth.json` and a working
  precision/recall/F1 scorer) and `data/stress_test.xlsx` (harder
  constructs -- Tables, 3D ranges, an external link, LET, a real circular
  reference -- used to prove each of those is handled correctly rather
  than silently mishandled)
- Both agent modes, wired to the same tool layer

Deliberately left as follow-up work, since "only what's needed" for a
baseline stops here:

- **Re-parsing on change** -- there's no file-watcher or diffing; re-run
  `WorkbookContext(path)` after the workbook changes.
- **Row-level granularity** -- column-level aggregation is the right
  granularity for tabular sheets, but the wrong one for hand-laid-out
  report sheets where several unrelated metrics share a column (see the
  `Summary` sheet discussion in `core/README.md`). Row- or block-level
  aggregation would need to be added for that case.
- **A UI** -- everything here is a Python API; there's no visualization
  front-end yet (Cytoscape.js/vis.js, as discussed earlier, would be the
  natural next piece).
