"""
Validates extraction accuracy against data/ground_truth.json.

Ground truth edges are (to, from) column pairs; we score set-overlap
(precision/recall/F1) rather than exact-kind matching, since "kind" labels
are a convenience, not the thing being tested.

Two things are deliberately excluded from the headline score, and reported
separately instead:
  - the one INDIRECT edge, since no static extractor can be expected to
    recover a dynamically-built reference;
  - the Summary sheet, because it's a hand-laid-out report (several
    unrelated metrics stacked in the same column) rather than a table --
    column-level aggregation is the wrong granularity there by design, not
    a bug. See core/README.md's "known limitations" section.

Usage:
    python validate.py [path_to_xlsx] [path_to_ground_truth_json]
"""
from __future__ import annotations

import json
import sys

from core import load_graph, to_edge_list


def _edge_set(edges, exclude_kind=None, exclude_sheet=None) -> set:
    out = set()
    for e in edges:
        if e.get("kind") == exclude_kind:
            continue
        if exclude_sheet and (e["to"].startswith(exclude_sheet + "!") or
                               e["from"].startswith(exclude_sheet + "!")):
            continue
        out.add((e["to"], e["from"]))
    return out


def main(xlsx_path: str, gt_path: str) -> None:
    with open(gt_path) as f:
        gt = json.load(f)

    graph, extraction = load_graph(xlsx_path)
    predicted = to_edge_list(graph)

    gt_scored = _edge_set(gt["edges"], exclude_kind="indirect_unresolvable_statically",
                           exclude_sheet="Summary")
    pred_scored = _edge_set(predicted, exclude_sheet="Summary")

    tp = gt_scored & pred_scored
    fn = gt_scored - pred_scored
    fp = pred_scored - gt_scored

    precision = len(tp) / len(pred_scored) if pred_scored else 0.0
    recall = len(tp) / len(gt_scored) if gt_scored else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0

    print(f"Ground-truth edges (scored):  {len(gt_scored)}")
    print(f"Extracted edges (total):      {len(pred_scored)}")
    print(f"True positives:               {len(tp)}")
    print(f"Missed (false negatives):     {len(fn)}")
    print(f"Spurious (false positives):   {len(fp)}")
    print(f"Precision: {precision:.3f}  Recall: {recall:.3f}  F1: {f1:.3f}")

    if fn:
        print("\nMissed edges:")
        for to, frm in sorted(fn):
            print(f"  {to} <- {frm}")
    if fp:
        print("\nSpurious edges:")
        for to, frm in sorted(fp):
            print(f"  {to} <- {frm}")

    indirect_gt = [e for e in gt["edges"] if e.get("kind") == "indirect_unresolvable_statically"]
    if indirect_gt:
        print(f"\nINDIRECT edges in ground truth (not scored above): {len(indirect_gt)}")
        print(f"Cells flagged by extractor as using INDIRECT: {len(extraction.indirect_cells)}")
        for sheet, cell, formula in extraction.indirect_cells:
            print(f"  {sheet}!{cell}: {formula}")

    summary_edges = [e for e in predicted if "Summary!" in e["to"] or "Summary!" in e["from"]]
    if summary_edges:
        print(f"\nSummary-sheet edges (not scored -- non-tabular report sheet, see README): "
              f"{len(summary_edges)}")
        for e in summary_edges:
            print(f"  {e['to']} <- {e['from']}  [{e['kind']}]")


if __name__ == "__main__":
    xlsx = sys.argv[1] if len(sys.argv) > 1 else "data/dependency_benchmark.xlsx"
    gt = sys.argv[2] if len(sys.argv) > 2 else "data/ground_truth.json"
    main(xlsx, gt)
