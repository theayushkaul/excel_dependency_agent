"""
Deterministic formula extraction.

Reads every formula cell in a workbook and turns it into raw, cell-level
"depends on" edges by tokenizing each formula and resolving every RANGE
operand -- plain cells, named ranges, Excel Table structured references,
and 3D sheet ranges -- down to (sheet, column_letter) pairs.

Nothing in this file uses an LLM. This is the layer that has to be exactly
right; the agents built on top only narrate what this layer already knows.

Anything this file cannot resolve is recorded, never silently dropped:
- `unresolved_refs`   -- a RANGE-shaped token that matched no known address,
                         table, or named range (previously: silently skipped)
- `external_refs`     -- a reference into another workbook file
- `indirect_cells`    -- a formula whose target is built at runtime
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

import openpyxl
from openpyxl.formula.tokenizer import Tokenizer
from openpyxl.utils import column_index_from_string, get_column_letter

# Plain cell/range reference, e.g. "Products!$E:$E", "C2", "'My Sheet'!$A$2:$A$10".
# Row number OR a second column is required -- a bare "A" or "x" with neither
# is not a valid standalone A1 reference in real Excel; it's almost always a
# LET/LAMBDA local variable name that happens to look like a column letter.
_RANGE_RE = re.compile(
    r"^(?:'(?P<sheet_q>[^']+)'|(?P<sheet>[A-Za-z0-9_.]+))?!?"
    r"\$?(?P<col1>[A-Z]{1,3})\$?(?P<row1>\d*)"
    r"(?::\$?(?P<col2>[A-Z]{1,3})\$?(?P<row2>\d*))?$"
)

# 3D range across multiple sheets, e.g. "Sheet1:Sheet3!A1" or "'Q1':'Q3'!A1".
_SHEET_RANGE_RE = re.compile(
    r"^(?:'(?P<s1q>[^']+)'|(?P<s1>[A-Za-z0-9_. ]+)):"
    r"(?:'(?P<s2q>[^']+)'|(?P<s2>[A-Za-z0-9_. ]+))!(?P<rest>.+)$"
)

# External workbook reference, e.g. "[Book2.xlsx]Sheet1!$A$1".
_EXTERNAL_RE = re.compile(r"^\[(?P<file>[^\]]+)\](?P<rest>.+)$")

# Excel Table structured reference, e.g. "Table1[Revenue]", "Table1[@Revenue]",
# "Table1[[Revenue]:[Cost]]", "Table1[#All]".
_STRUCTURED_RE = re.compile(r"^(?P<table>[A-Za-z_][A-Za-z0-9_.]*)\[(?P<spec>.+)\]$")

# A bare 1-3 letter word with no row number, no colon, no '!' -- e.g. "x" or "A".
# This can never be a valid standalone A1 reference (a real whole-column ref
# needs the colon, as in "A:A"), so if it isn't a resolvable named range
# either, it's almost always a LET/LAMBDA local binding name, not a broken
# reference. Tracked separately so it doesn't drown out real unresolved_refs.
_BARE_WORD_RE = re.compile(r"^[A-Za-z]{1,3}$")


@dataclass
class RawEdge:
    from_sheet: str
    from_cell: str
    to_sheet: str
    to_cols: list
    via_named_range: Optional[str] = None
    via_table: Optional[str] = None


@dataclass
class ExtractionResult:
    edges: list = field(default_factory=list)
    indirect_cells: list = field(default_factory=list)   # (sheet, cell, formula)
    external_refs: list = field(default_factory=list)    # (sheet, cell, raw_token, file)
    unresolved_refs: list = field(default_factory=list)  # (sheet, cell, raw_token)
    local_names: list = field(default_factory=list)      # (sheet, cell, raw_token) -- LET/LAMBDA, benign
    header_map: dict = field(default_factory=dict)       # sheet -> {col_letter: header_name}


def _parse_range_token(token_value: str, current_sheet: str):
    """Plain cell/range -> (sheet, [col_letters]) or None if not address-shaped."""
    m = _RANGE_RE.match(token_value.strip())
    if not m:
        return None
    col1, col2, row1 = m.group("col1"), m.group("col2"), m.group("row1")
    if not row1 and not col2:
        return None  # bare column letter, no row, no range -- not a real reference
    sheet = m.group("sheet_q") or m.group("sheet") or current_sheet
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
    return dn.attr_text.split(",")[0]  # first area only


def _index_tables(wb) -> dict:
    """table_name.lower() -> {"sheet", "col_letters" (ordered), "name_to_col"}."""
    index = {}
    for sheet in wb.sheetnames:
        ws = wb[sheet]
        for tbl in getattr(ws, "tables", {}).values():
            min_col, min_row, max_col, max_row = openpyxl.utils.cell.range_boundaries(tbl.ref)
            col_letters = [get_column_letter(c) for c in range(min_col, max_col + 1)]
            name_to_col = {}
            for c, letter in zip(range(min_col, max_col + 1), col_letters):
                header = ws.cell(row=min_row, column=c).value
                if header is not None:
                    name_to_col[str(header)] = letter
            index[tbl.name.lower()] = {
                "sheet": sheet, "col_letters": col_letters, "name_to_col": name_to_col,
            }
    return index


def _parse_structured_ref(raw: str, table_index: dict):
    """'Table1[Revenue]' etc -> (sheet, [col_letters]) or None."""
    m = _STRUCTURED_RE.match(raw.strip())
    if not m:
        return None
    info = table_index.get(m.group("table").lower())
    if info is None:
        return None
    spec = m.group("spec").strip()
    if spec.startswith("@"):
        spec = spec[1:]
    spec = spec.replace("[", "").replace("]", "").strip()
    if spec == "" or spec.startswith("#"):
        return info["sheet"], list(info["col_letters"])
    if ":" in spec:
        left, right = (s.strip() for s in spec.split(":", 1))
        l, r = info["name_to_col"].get(left), info["name_to_col"].get(right)
        if not (l and r):
            return None
        i1, i2 = column_index_from_string(l), column_index_from_string(r)
        lo, hi = sorted((i1, i2))
        return info["sheet"], [get_column_letter(i) for i in range(lo, hi + 1)]
    col = info["name_to_col"].get(spec)
    return (info["sheet"], [col]) if col else None


def _parse_sheet_range(raw: str, current_sheet: str, sheet_order: list):
    """'Sheet1:Sheet3!A1' -> [(sheet, [cols]), ...] for every sheet in the span, or None."""
    m = _SHEET_RANGE_RE.match(raw.strip())
    if not m:
        return None
    s1 = m.group("s1q") or m.group("s1")
    s2 = m.group("s2q") or m.group("s2")
    if s1 not in sheet_order or s2 not in sheet_order:
        return None
    i1, i2 = sheet_order.index(s1), sheet_order.index(s2)
    lo, hi = sorted((i1, i2))
    parsed = _parse_range_token(m.group("rest"), current_sheet)
    if parsed is None:
        return None
    _, cols = parsed
    return [(sheet_order[i], cols) for i in range(lo, hi + 1)]


def _read_header_map(ws) -> dict:
    headers = {}
    for cell in ws[1]:
        if cell.value is not None:
            headers[cell.column_letter] = str(cell.value)
    return headers


def extract_workbook(path: str) -> ExtractionResult:
    wb = openpyxl.load_workbook(path, data_only=False)
    result = ExtractionResult()
    table_index = _index_tables(wb)
    sheet_order = wb.sheetnames

    for sheet in sheet_order:
        result.header_map[sheet] = _read_header_map(wb[sheet])

    for sheet in sheet_order:
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

                    ext = _EXTERNAL_RE.match(raw)
                    if ext:
                        result.external_refs.append((sheet, cell.coordinate, raw, ext.group("file")))
                        continue

                    targets = None  # list of (to_sheet, cols); set by whichever branch resolves it
                    via_named = via_table = None

                    plain = _parse_range_token(raw, sheet)
                    if plain is not None:
                        targets = [plain]
                    else:
                        sheet_span = _parse_sheet_range(raw, sheet, sheet_order)
                        if sheet_span is not None:
                            targets = sheet_span
                        else:
                            structured = _parse_structured_ref(raw, table_index)
                            if structured is not None:
                                targets = [structured]
                                via_table = raw.split("[", 1)[0]
                            else:
                                resolved = _resolve_named_range(raw, wb.defined_names)
                                if resolved is not None:
                                    reparsed = _parse_range_token(resolved, sheet)
                                    if reparsed is not None:
                                        targets = [reparsed]
                                        via_named = raw

                    if targets is None:
                        bucket = result.local_names if _BARE_WORD_RE.match(raw) else result.unresolved_refs
                        bucket.append((sheet, cell.coordinate, raw))
                        continue

                    for to_sheet, cols in targets:
                        result.edges.append(RawEdge(
                            from_sheet=sheet, from_cell=cell.coordinate,
                            to_sheet=to_sheet, to_cols=cols,
                            via_named_range=via_named, via_table=via_table,
                        ))
    return result
