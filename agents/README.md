# agents/

Two agent modes sit on top of `core/`, sharing the same `WorkbookContext`
and the same tool functions. Neither one is allowed to invent a dependency
that `core/tools.py` didn't return -- the LLM's job in both cases is to
*phrase* facts, not to *find* them.

## `memory.py`

- **`DocStore`** -- the documentation cache. Never authoritative; always
  traceable back to the graph. If the workbook changes, the graph updates
  immediately on next parse, but this cache can lag until the deep agent
  re-runs.
- **`ProgressTracker`** -- the deep agent's own scratchpad: which columns
  it has already documented in this pass, so a long run can be interrupted
  and resumed.

## `deep_agent.py` -- offline, batch

Run this once per workbook (or after you detect the workbook changed).
It walks every column, gathers that column's formula + precedents +
dependents deterministically, and makes **one LLM call per column** to
phrase an explanation. No tool-calling loop needed here -- by the time the
model is called, every fact it needs is already in the prompt.

```python
from core.tools import WorkbookContext
from agents import DocStore, ProgressTracker, DeepDocumentationAgent

ctx = WorkbookContext("data/dependency_benchmark.xlsx")
doc_store = DocStore("data/doc_store.json")
progress = ProgressTracker("data/progress.json")

agent = DeepDocumentationAgent(ctx, doc_store, progress)
agent.run(limit=5)   # documents 5 not-yet-done columns; omit limit to do all
```

## `react_agent.py` -- online, per-question

Run this per user question. It's a real think -> tool call -> observe loop
(capped at `MAX_TURNS`), with `doc_lookup` as a fast path into the cache
before it falls back to live graph queries.

```python
from agents import ReActAgent

agent = ReActAgent(ctx, doc_store)
print(agent.ask("What does Sales.TaxRate depend on, and is any of that dynamic?"))
```

## Requires an API key

Both agents call the Anthropic API and need `ANTHROPIC_API_KEY` set in
the environment. `core/` needs no key at all -- extraction, the graph, and
`validate.py` all run offline.
