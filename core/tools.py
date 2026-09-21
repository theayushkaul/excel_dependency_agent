"""
Read-only query tools over a loaded column dependency graph.

These are the *only* things an agent is allowed to call to answer a
factual question about the workbook -- every claim an agent makes should
trace back to one of these calls. Keeping them dumb and literal is the
point: no fuzzing, no inference, just graph lookups and formula text.
"""
from __future__ import annotations

import networkx as nx

from .graph import load_graph


class WorkbookContext:
    """Parses a workbook once (on construction) and holds the resulting graph."""

    def __init__(self, path: str):
        self.path = path
        self.graph, self.extraction = load_graph(path)

    def list_sheets(self) -> list:
        return sorted(self.extraction.header_map.keys())

    def list_columns(self, sheet: str) -> list:
        return [f"{sheet}!{col} ({name})"
                for col, name in sorted(self.extraction.header_map.get(sheet, {}).items())]

    def resolve_column(self, sheet: str, name_or_letter: str):
        """Accepts a column letter ('F') or a header name ('UnitPrice'), case-insensitive."""
        headers = self.extraction.header_map.get(sheet, {})
        if name_or_letter in headers:
            return f"{sheet}!{name_or_letter}"
        for col, header in headers.items():
            if header.lower() == name_or_letter.lower():
                return f"{sheet}!{col}"
        return None

    def get_precedents(self, node: str, max_depth: int = 1) -> list:
        """Columns this column's formulas depend on, up to max_depth hops away."""
        if node not in self.graph:
            return []
        visited, frontier = set(), {node}
        for _ in range(max_depth):
            nxt = set()
            for n in frontier:
                nxt |= set(self.graph.successors(n))
            nxt -= visited
            nxt.discard(node)
            if not nxt:
                break
            visited |= nxt
            frontier = nxt
        return sorted(visited)

    def get_dependents(self, node: str) -> list:
        """Columns whose formulas reference this column (one hop)."""
        if node not in self.graph:
            return []
        return sorted(self.graph.predecessors(node))

    def get_column_info(self, node: str) -> dict:
        """Header name, a sample formula, row count, and whether the column
        is a stretched pattern (same formula copied down every row)."""
        if node not in self.graph:
            return {}
        return dict(self.graph.nodes[node])

    def find_path(self, from_node: str, to_node: str) -> list:
        """A concrete chain of dependency from from_node down to to_node, if any."""
        try:
            return nx.shortest_path(self.graph, from_node, to_node)
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return []

    def indirect_warnings(self) -> list:
        """Cells using INDIRECT -- the one case this extractor cannot fully
        resolve statically. Always surface these rather than silently
        under-reporting a column's true dependencies."""
        return list(self.extraction.indirect_cells)
