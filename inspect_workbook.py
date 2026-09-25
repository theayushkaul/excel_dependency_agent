"""
Point this at any workbook (not just the benchmark) to see exactly what
the extractor resolved and what it couldn't -- the three warning lists are
the first thing to check if extraction looks incomplete on a real file.

Usage:
    python inspect_workbook.py path/to/real_file.xlsx
"""
import sys

from core.tools import WorkbookContext


def main(path: str) -> None:
    ctx = WorkbookContext(path)

    print(f"Sheets: {ctx.list_sheets()}")
    print(f"Column-level nodes: {ctx.graph.number_of_nodes()}")
    print(f"Column-level edges: {ctx.graph.number_of_edges()}")

    cycles = ctx.find_cycles()
    print(f"\nCircular references: {len(cycles)}")
    for c in cycles:
        print(f"  {' -> '.join(c)} -> {c[0]}")

    indirect = ctx.indirect_warnings()
    print(f"\nINDIRECT cells (unresolvable statically): {len(indirect)}")
    for sheet, cell, formula in indirect[:20]:
        print(f"  {sheet}!{cell}: {formula}")

    external = ctx.external_ref_warnings()
    print(f"\nExternal-workbook references (out of scope by construction): {len(external)}")
    for sheet, cell, raw, file in external[:20]:
        print(f"  {sheet}!{cell}: {raw}  (file: {file})")

    unresolved = ctx.unresolved_ref_warnings()
    print(f"\nUnresolved references -- investigate these, they mean real "
          f"dependencies may be missing: {len(unresolved)}")
    for sheet, cell, raw in unresolved[:30]:
        print(f"  {sheet}!{cell}: {raw!r}")
    if len(unresolved) > 30:
        print(f"  ... and {len(unresolved) - 30} more")

    print(f"\nLET/LAMBDA-style local names (benign, filtered out above): "
          f"{ctx.local_name_count()}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python inspect_workbook.py path/to/file.xlsx")
        sys.exit(1)
    main(sys.argv[1])
