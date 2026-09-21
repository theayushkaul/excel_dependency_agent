"""
Deep agent: an offline documentation pass over an entire workbook.

Unlike the ReAct agent (react_agent.py), this agent doesn't reason
turn-by-turn about which tool to call -- all its inputs (formula, header,
precedents, dependents) are already gathered deterministically before the
one LLM call per column. The LLM's only job is to phrase that context in
plain language, grounded in the real formula, not to go find facts itself.

Progress is tracked in a ProgressTracker so a long run can be interrupted
and resumed without redoing already-documented columns.
"""
from __future__ import annotations

from typing import Optional

import anthropic

from core.tools import WorkbookContext
from .memory import DocStore, ProgressTracker

MODEL = "claude-sonnet-4-6"

SYSTEM_PROMPT = """You write short, precise, plain-language explanations of what a
spreadsheet column does, for someone auditing an unfamiliar workbook.

Rules:
- Base the explanation ONLY on the formula and dependency facts given to you.
  Never invent business meaning that isn't supported by them.
- Quote the actual formula (or the shape of it) rather than describing it vaguely.
- Mention what it depends on and, if given, what depends on it.
- 2-4 sentences. No preamble, no headers, no markdown."""


class DeepDocumentationAgent:
    def __init__(self, ctx: WorkbookContext, doc_store: DocStore,
                 progress: ProgressTracker, client: Optional[anthropic.Anthropic] = None):
        self.ctx = ctx
        self.doc_store = doc_store
        self.progress = progress
        self.client = client or anthropic.Anthropic()

    def _build_context(self, node: str) -> str:
        info = self.ctx.get_column_info(node)
        precedents = self.ctx.get_precedents(node)
        dependents = self.ctx.get_dependents(node)
        return "\n".join([
            f"Column: {node} (header: {info.get('header', node.split('!')[1])})",
            f"Sample formula: {info.get('sample', '(no formula -- source data column)')}",
            f"Stretched pattern (same formula every row): {info.get('stretched', False)}",
            f"Depends on: {', '.join(precedents) or '(nothing -- source column)'}",
            f"Depended on by: {', '.join(dependents) or '(nothing downstream)'}",
        ])

    def document_column(self, node: str) -> str:
        resp = self.client.messages.create(
            model=MODEL, max_tokens=300, system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": self._build_context(node)}],
        )
        explanation = "".join(b.text for b in resp.content if b.type == "text")
        self.doc_store.set(node, explanation, self.ctx.get_column_info(node).get("sample", ""))
        self.progress.mark_done(node)
        return explanation

    def run(self, limit: Optional[int] = None) -> dict:
        """Documents every not-yet-done column (or up to `limit` of them).
        Safe to interrupt and re-run -- already-documented columns are skipped."""
        todo = self.progress.remaining(sorted(self.ctx.graph.nodes))
        if limit:
            todo = todo[:limit]
        return {node: self.document_column(node) for node in todo}
