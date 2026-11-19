"""E6: data-flow and control precision/recall against human gold annotations (G)."""

from __future__ import annotations

import json
from itertools import combinations
from pathlib import Path
from typing import Any

SETS = ("reads", "writes", "performs", "goes_to")
GOLD_PROGRAMS = {"PAYROLL": "D1", "INVENTORY": "D1", "ACCTPOST": "D1", "MERGE2": "D1", "LOANCALC": "D1",
                 "FALLTHRU": "D2", "REDEF": "D2"}


def load_gold(directory: Path) -> dict[str, dict[str, Any]]:
    """annotator -> gold file; TEMPLATE.json and files without an annotator are ignored."""
    out: dict[str, dict[str, Any]] = {}
    for p in sorted(directory.glob("*.json")):
        data = json.loads(p.read_text("utf-8"))
        if p.name != "TEMPLATE.json" and data.get("annotator"):
            out[data["annotator"]] = data
    return out


def annotated(para: dict[str, Any]) -> bool:
    return any(para.get(k) for k in SETS) or para.get("falls_through_to") is not None or bool(para.get("note"))


class Prf:
    def __init__(self) -> None:
        self.tp = self.fp = self.fn = 0

    def add(self, predicted: set[str], gold: set[str]) -> None:
        self.tp += len(predicted & gold)
        self.fp += len(predicted - gold)
        self.fn += len(gold - predicted)

    def scores(self) -> dict[str, float | int]:
        p = self.tp / max(self.tp + self.fp, 1)
        r = self.tp / max(self.tp + self.fn, 1)
        f = 0.0
        if p + r:
            f = 2 * p * r / (p + r)
        return {"precision": round(p, 4), "recall": round(r, 4), "f1": round(f, 4), "tp": self.tp, "fp": self.fp,
                "fn": self.fn}


def score(units_by_program: dict[str, dict[str, dict[str, Any]]], gold: dict[str, dict[str, Any]],
          source: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    overall = {k: Prf() for k in SETS}
    per_program: dict[str, dict[str, Any]] = {}
    fall_ok = fall_n = 0
    failures: list[dict[str, Any]] = []
    for annotator, data in sorted(gold.items()):
        for prog, entry in sorted(data["programs"].items()):
            units = units_by_program.get(prog, {})
            local = {k: Prf() for k in SETS}
            for name, para in sorted(entry["paragraphs"].items()):
                if not annotated(para):
                    continue
                u = units.get(name, {})
                for k in SETS:
                    predicted, truth = set(u.get(k) or []), set(para.get(k) or [])
                    overall[k].add(predicted, truth)
                    local[k].add(predicted, truth)
                    for miss in sorted(truth - predicted):
                        failures.append({"metric": "E6", "source": source, "annotator": annotator, "program": prog,
                                         "unit": name, "set": k, "missing": miss})
                fall_n += 1
                fall_ok += u.get("falls_through_to") == para.get("falls_through_to")
            per_program[f"{prog}@{annotator}"] = {k: v.scores() for k, v in local.items()}
    return ({"overall": {k: v.scores() for k, v in overall.items()}, "per_program": per_program,
             "falls_through_to_accuracy": round(fall_ok / max(fall_n, 1), 4), "paragraphs": fall_n}, failures)


def agreement(gold: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Pairwise F1 between annotators on the paragraphs both annotated (symmetric)."""
    out: dict[str, Any] = {}
    for a, b in combinations(sorted(gold), 2):
        acc = {k: Prf() for k in SETS}
        fall_ok = fall_n = 0
        for prog, entry in gold[a]["programs"].items():
            other = gold[b]["programs"].get(prog, {}).get("paragraphs", {})
            for name, pa in entry["paragraphs"].items():
                pb = other.get(name)
                if pb is None or not annotated(pa) or not annotated(pb):
                    continue
                for k in SETS:
                    acc[k].add(set(pa.get(k) or []), set(pb.get(k) or []))
                fall_n += 1
                fall_ok += pa.get("falls_through_to") == pb.get("falls_through_to")
        out[f"{a}~{b}"] = {**{k: v.scores()["f1"] for k, v in acc.items()},
                           "falls_through_to": round(fall_ok / max(fall_n, 1), 4), "paragraphs": fall_n}
    return out
