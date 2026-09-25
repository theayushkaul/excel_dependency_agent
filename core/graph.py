"""
Column-level dependency graph.

Cell-level RawEdges from extractor.py are collapsed to column-level edges
(the "400 identical rows -> one node" step) and loaded into a networkx
DiGraph. This is the graph every tool and every agent queries -- never the
raw cell-level edges directly, which would be unreadable at any real scale.

Edge convention: g.add_edge(u, v) means "column u's formulas reference
column v", i.e. u depends on v. So successors(u) = u's precedents,
predecessors(v) = v's dependents.
"""
from __future__ import annotations

import re
from collections import defaultdict

import networkx as nx
import openpyxl

from .extractor import ExtractionResult, extract_workbook  # noqa: F401 (re-exported)

_ROW_NUM_RE = re.compile(r"\d+$")
_NORMALIZE_RE = re.compile(r"([A-Za-z]{1,3})\$?(\d+)")


def _col_letter(cell_coord: str) -> str:
    return _ROW_NUM_RE.sub("", cell_coord)


def _classify(from_sheet: str, to_sheet: str, via_named, via_table=None) -> str:
    if via_table:
        return "table_ref"
    if via_named:
        return "named_range"
    return "same_sheet" if from_sheet == to_sheet else "cross_sheet"


def build_column_graph(extraction: ExtractionResult) -> nx.DiGraph:
    g = nx.DiGraph()
    edge_kinds = defaultdict(set)

    for e in extraction.edges:
        from_col = _col_letter(e.from_cell)
        u = f"{e.from_sheet}!{from_col}"
        for col in e.to_cols:
            v = f"{e.to_sheet}!{col}"
            if u == v:
                continue  # formula referencing its own column -- ignore as noise
            g.add_edge(u, v)
            edge_kinds[(u, v)].add(_classify(e.from_sheet, e.to_sheet, e.via_named_range, e.via_table))

    for (u, v), kinds in edge_kinds.items():
        g.edges[u, v]["kinds"] = sorted(kinds)

    for node in g.nodes:
        sheet, col = node.split("!")
        g.nodes[node]["sheet"] = sheet
        g.nodes[node]["column"] = col
        g.nodes[node]["header"] = extraction.header_map.get(sheet, {}).get(col, col)

    return g


def detect_stretched_columns(path: str, extraction: ExtractionResult) -> dict:
    """
    For each (sheet, column) with formulas in more than one row: does every
    row use the same formula template with row numbers normalized away?
    That's the signal a good extractor uses to say "these 400 rows are one
    pattern" instead of 400 unrelated formulas.
    """
    wb = openpyxl.load_workbook(path, data_only=False)
    by_col = defaultdict(list)
    for sheet in wb.sheetnames:
        for row in wb[sheet].iter_rows():
            for cell in row:
                if cell.data_type == "f" and isinstance(cell.value, str):
                    by_col[f"{sheet}!{_col_letter(cell.coordinate)}"].append(cell.value)

    def normalize(f: str) -> str:
        return _NORMALIZE_RE.sub(lambda m: m.group(1) + "#", f)

    out = {}
    for key, formulas in by_col.items():
        templates = {normalize(f) for f in formulas}
        out[key] = {
            "stretched": len(templates) == 1 and len(formulas) > 1,
            "sample": formulas[0],
            "n_rows": len(formulas),
        }
    return out


def find_cycles(graph: nx.DiGraph) -> list:
    """Every circular-reference chain in the graph -- Excel normally throws
    a circular-reference warning for these. Each result is a list of nodes
    forming one cycle (A -> B -> C -> A)."""
    return list(nx.simple_cycles(graph))


def load_graph(path: str):
    """One-shot convenience: parse a workbook straight into a column graph."""
    extraction = extract_workbook(path)
    graph = build_column_graph(extraction)
    for node, info in detect_stretched_columns(path, extraction).items():
        if node in graph.nodes:
            graph.nodes[node].update(info)
    return graph, extraction


def _label(graph: nx.DiGraph, node: str) -> str:
    """'Sales!F' -> 'Sales!UnitPrice' when a header name is known, else the
    raw column letter. Ground truth is written in header names, so this is
    what makes the two comparable."""
    sheet, col = node.split("!")
    header = graph.nodes[node].get("header")
    return f"{sheet}!{header}" if header else node


def to_edge_list(graph: nx.DiGraph, use_headers: bool = True) -> list:
    """Export edges as {"to":..., "from":..., "kind":...} dicts -- the same
    shape as data/ground_truth.json, so validate.py can diff the two directly."""
    out = []
    for u, v, data in graph.edges(data=True):
        to_ = _label(graph, u) if use_headers else u
        from_ = _label(graph, v) if use_headers else v
        out.append({"to": to_, "from": from_, "kind": "+".join(data.get("kinds", ["unknown"]))})
    return out
