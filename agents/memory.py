"""
Two small, deliberately separate JSON-backed stores.

DocStore is the *documentation cache* -- natural-language explanations the
deep agent generates, grounded in real formulas. It is never authoritative:
the ReAct agent can always fall back to core.tools for the live graph.

ProgressTracker is the deep agent's own *scratchpad* -- which columns it
has already documented in this pass. This is what lets a long documentation
run resume after being interrupted, instead of starting over.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone


class DocStore:
    def __init__(self, path: str):
        self.path = path
        self._data: dict = {}
        if os.path.exists(path):
            with open(path) as f:
                self._data = json.load(f)

    def get(self, node: str):
        return self._data.get(node)

    def set(self, node: str, explanation: str, sample_formula: str = "") -> None:
        self._data[node] = {
            "explanation": explanation,
            "sample_formula": sample_formula,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        self._save()

    def all(self) -> dict:
        return dict(self._data)

    def _save(self) -> None:
        with open(self.path, "w") as f:
            json.dump(self._data, f, indent=2)


class ProgressTracker:
    def __init__(self, path: str):
        self.path = path
        self._done: set = set()
        if os.path.exists(path):
            with open(path) as f:
                self._done = set(json.load(f))

    def is_done(self, node: str) -> bool:
        return node in self._done

    def mark_done(self, node: str) -> None:
        self._done.add(node)
        self._save()

    def remaining(self, all_nodes: list) -> list:
        return [n for n in all_nodes if n not in self._done]

    def reset(self) -> None:
        self._done = set()
        self._save()

    def _save(self) -> None:
        with open(self.path, "w") as f:
            json.dump(sorted(self._done), f, indent=2)
