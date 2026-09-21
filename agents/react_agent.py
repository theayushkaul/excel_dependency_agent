"""
ReAct agent: answers one question at a time by reasoning about which
deterministic tool to call, observing the result, and repeating until it
can answer -- the classic think -> act -> observe loop.

It shares core.tools.WorkbookContext with the deep agent, and checks the
doc_store cache first (fast path) before falling back to live graph
queries. Every fact it states should be traceable to a tool call in the
transcript -- it never guesses a dependency that no tool call returned.
"""
from __future__ import annotations

import json
from typing import Optional

import anthropic

from core.tools import WorkbookContext
from .memory import DocStore

MODEL = "claude-sonnet-4-6"
MAX_TURNS = 6

SYSTEM_PROMPT = """You answer questions about an Excel workbook's formula
dependencies. You have tools that query a dependency graph built by parsing
the workbook's actual formulas -- use them rather than guessing.

Always check doc_lookup first for a column you're asked about; it's a
cached explanation and is often enough on its own. Fall back to the graph
tools (get_precedents, get_dependents, get_column_info, find_path) when you
need something the cache doesn't cover, or to double-check a claim.

Ground every answer in what the tools actually returned. If a formula uses
INDIRECT, say so explicitly rather than stating a dependency you can't
support -- the tools will tell you when that's the case.
Keep answers short and concrete."""

TOOLS = [
    {"name": "list_sheets", "description": "List every sheet name in the workbook.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "list_columns", "description": "List columns (letter + header) in a sheet.",
     "input_schema": {"type": "object", "properties": {"sheet": {"type": "string"}},
                       "required": ["sheet"]}},
    {"name": "resolve_column",
     "description": "Turn a sheet + column letter or header name into a graph node id "
                     "like 'Sales!F'. Call this before any other tool that takes a node.",
     "input_schema": {"type": "object", "properties": {
         "sheet": {"type": "string"}, "name_or_letter": {"type": "string"}},
         "required": ["sheet", "name_or_letter"]}},
    {"name": "get_precedents",
     "description": "Columns this column's formulas depend on (what it references).",
     "input_schema": {"type": "object", "properties": {
         "node": {"type": "string"}, "max_depth": {"type": "integer", "default": 1}},
         "required": ["node"]}},
    {"name": "get_dependents",
     "description": "Columns whose formulas reference this column (what depends on it).",
     "input_schema": {"type": "object", "properties": {"node": {"type": "string"}},
                       "required": ["node"]}},
    {"name": "get_column_info",
     "description": "Header name, a sample formula, and stretched-pattern info for a column.",
     "input_schema": {"type": "object", "properties": {"node": {"type": "string"}},
                       "required": ["node"]}},
    {"name": "find_path",
     "description": "A concrete dependency chain from one column down to another, if one exists.",
     "input_schema": {"type": "object", "properties": {
         "from_node": {"type": "string"}, "to_node": {"type": "string"}},
         "required": ["from_node", "to_node"]}},
    {"name": "doc_lookup",
     "description": "Cached natural-language explanation of a column, if the deep agent has "
                     "already documented it. Cheaper than reasoning from scratch -- try this first.",
     "input_schema": {"type": "object", "properties": {"node": {"type": "string"}},
                       "required": ["node"]}},
]


class ReActAgent:
    def __init__(self, ctx: WorkbookContext, doc_store: DocStore,
                 client: Optional[anthropic.Anthropic] = None):
        self.ctx = ctx
        self.doc_store = doc_store
        self.client = client or anthropic.Anthropic()
        self._dispatch = {
            "list_sheets": lambda **kw: self.ctx.list_sheets(),
            "list_columns": lambda **kw: self.ctx.list_columns(kw["sheet"]),
            "resolve_column": lambda **kw: self.ctx.resolve_column(kw["sheet"], kw["name_or_letter"]),
            "get_precedents": lambda **kw: self.ctx.get_precedents(kw["node"], kw.get("max_depth", 1)),
            "get_dependents": lambda **kw: self.ctx.get_dependents(kw["node"]),
            "get_column_info": lambda **kw: self.ctx.get_column_info(kw["node"]),
            "find_path": lambda **kw: self.ctx.find_path(kw["from_node"], kw["to_node"]),
            "doc_lookup": lambda **kw: self.doc_store.get(kw["node"]) or "(not yet documented)",
        }

    def _run_tool(self, name: str, tool_input: dict):
        return self._dispatch[name](**tool_input)

    def ask(self, question: str) -> str:
        messages = [{"role": "user", "content": question}]
        for _ in range(MAX_TURNS):
            resp = self.client.messages.create(
                model=MODEL, max_tokens=1024, system=SYSTEM_PROMPT,
                tools=TOOLS, messages=messages,
            )
            messages.append({"role": "assistant", "content": resp.content})

            tool_uses = [b for b in resp.content if b.type == "tool_use"]
            if not tool_uses:
                return "".join(b.text for b in resp.content if b.type == "text")

            tool_results = []
            for block in tool_uses:
                try:
                    result = self._run_tool(block.name, block.input)
                except Exception as exc:  # noqa: BLE001 -- surface the error to the model, don't crash
                    result = f"error: {exc}"
                tool_results.append({
                    "type": "tool_result", "tool_use_id": block.id,
                    "content": json.dumps(result, default=str),
                })
            messages.append({"role": "user", "content": tool_results})

        return "I wasn't able to reach a grounded answer within the tool-call budget."
