"""
Deterministic formula extraction.

Reads every formula cell in a workbook and turns it into raw, cell-level
"depends on" edges by tokenizing each formula and resolving every RANGE
operand -- including named ranges -- down to a (sheet, column_letter) pair.

Nothing in this file uses an LLM. This is the layer that has to be exactly
right; the agents built on top only narrate what this layer already knows.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

import openpyxl
from openpyxl.formula.tokenizer import Tokenizer
from openpyxl.utils import column_index_from_string, get_column_letter

# Matches a cell/range reference token as emitted by openpyxl's formula
# tokenizer, e.g. "Products!$E:$E", "C2", "'My Sheet'!$A$2:$A$10".
_RANGE_RE = re.compile(
    r"^(?:'(?P<sheet_q>[^']+)'|(?P<sheet>[A-Za-z0-9_.]+))?!?"
    r"\$?(?P<col1>[A-Z]{1,3})\$?(?P<row1>\d*)"
    r"(?::\$?(?P<col2>[A-Z]{1,3})\$?(?P<row2>\d*))?$"
)


@dataclass
class RawEdge:
    from_sheet: str
    from_cell: str
    to_sheet: str
    to_cols: list  # one or more column letters (a range can span several)
    via_named_range: Optional[str] = None


@dataclass
class ExtractionResult:
    edges: list = field(default_factory=list)
    # cells whose formula calls INDIRECT -- flagged because part of their
    # true dependency is only resolvable at runtime, not by static parsing
    indirect_cells: list = field(default_factory=list)  # (sheet, cell, formula)
    header_map: dict = field(default_factory=dict)  # sheet -> {col_letter: header_name}


def _parse_range_token(token_value: str, current_sheet: str):
    """Turn one tokenizer RANGE operand into (sheet, [col_letters]) or None."""
    m = _RANGE_RE.match(token_value.strip())
    if not m:
        return None
    sheet = m.group("sheet_q") or m.group("sheet") or current_sheet
    col1, col2 = m.group("col1"), m.group("col2")
    if col2 and col2 != col1:
        i1, i2 = column_index_from_string(col1), column_index_from_string(col2)
        lo, hi = sorted((i1, i2))
        cols = [get_column_letter(i) for i in range(lo, hi + 1)]
    else:
        cols = [col1]
    return sheet, cols


def _resolve_named_range(name: str, defined_names) -> Optional[str]:
    dn = defined_names.get(name)
    if dn is None or dn.attr_text is None:
        return None
    return dn.attr_text.split(",")[0]  # first area only; good enough for v1


def _read_header_map(ws) -> dict:
    headers = {}
    for cell in ws[1]:
        if cell.value is not None:
            headers[cell.column_letter] = str(cell.value)
    return headers


def extract_workbook(path: str) -> ExtractionResult:
    wb = openpyxl.load_workbook(path, data_only=False)
    result = ExtractionResult()

    for sheet in wb.sheetnames:
        result.header_map[sheet] = _read_header_map(wb[sheet])

    for sheet in wb.sheetnames:
        ws = wb[sheet]
        for row in ws.iter_rows():
            for cell in row:
                if cell.data_type != "f" or not isinstance(cell.value, str):
                    continue
                formula = cell.value
                if "INDIRECT(" in formula.upper():
                    result.indirect_cells.append((sheet, cell.coordinate, formula))

                for tok in Tokenizer(formula).items:
                    if tok.type != "OPERAND" or tok.subtype != "RANGE":
                        continue
                    raw = tok.value
                    via_named = None
                    parsed = _parse_range_token(raw, sheet)
                    if parsed is None:
                        resolved = _resolve_named_range(raw, wb.defined_names)
                        if resolved is None:
                            continue  # not an address and not a known name -> skip
                        parsed = _parse_range_token(resolved, sheet)
                        via_named = raw
                        if parsed is None:
                            continue
                    to_sheet, cols = parsed
                    result.edges.append(RawEdge(
                        from_sheet=sheet, from_cell=cell.coordinate,
                        to_sheet=to_sheet, to_cols=cols, via_named_range=via_named,
                    ))
    return result
