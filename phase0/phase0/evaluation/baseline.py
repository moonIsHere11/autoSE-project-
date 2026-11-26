"""E7 baseline: Phase 1's tolerant analyser (`phase1 analyze`), mapped onto the KB schema and scored
with the same oracles and the same O1/O2 runs as Phase 0."""

from __future__ import annotations

import json
import subprocess
import sys
from typing import Any

from phase0.evaluation.datasets import Built
from phase0.evaluation.e2_e4_control import ControlKb
from phase0.target import REPO


def analyse(b: Built) -> dict[str, Any]:
    """Runs the real Phase 1 CLI on the same workspace; it writes W/phase1/index.json."""
    cmd = [sys.executable, str(REPO / "phase1" / "bin" / "phase1"), "analyze", "--workspace", str(b.ws)]
    subprocess.run(cmd, check=True, capture_output=True, text=True)
    data: dict[str, Any] = json.loads((b.ws / "phase1" / "index.json").read_text("utf-8"))
    return data


def units(index: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for u in index["units"]:
        out.append({"unit_id": u["unit_id"], "kind": u["kind"], "span": u["span"], "reads": u["reads"],
                    "writes": u["writes"], "performs": u["performs"], "goes_to": u.get("gotos", []),
                    "falls_through_to": u["falls_through_to"], "section": u.get("section")})
    return out


def edges(us: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for u in us:
        line = u["span"]["start_line"]
        out += [{"src": u["unit_id"], "dst": p, "kind": "perform", "line": line} for p in u["performs"]]
        out += [{"src": u["unit_id"], "dst": g, "kind": "goto", "line": line} for g in u["goes_to"]]
        if u["falls_through_to"]:
            out.append({"src": u["unit_id"], "dst": u["falls_through_to"], "kind": "fallthrough", "line": line})
    return out


def control_kb(us: list[dict[str, Any]]) -> ControlKb:
    """Phase 1 records no line for each PERFORM, so its perform sites are keyed by unit only: the
    loop re-entry rule then accepts any target the unit performs (slightly in Phase 1's favour)."""
    kb = ControlKb.load(us, edges(us))
    for u in us:
        for line in range(u["span"]["start_line"], u["span"]["end_line"] + 1):
            if u["performs"]:
                kb.perform_sites[(u["unit_id"], line)] = set(u["performs"])
    return kb


def fields(index: dict[str, Any]) -> list[dict[str, Any]]:
    """Phase 1 fields in the KB's shape; no layout facts (offset, byte length) exist there."""
    out: list[dict[str, Any]] = []
    for f in index["fields"]:
        out.append({"field_id": f["field_id"], "name": f["name"], "level": f["level"], "parent": f["parent"],
                    "pic": f["pic"], "usage": f["usage"], "semantic_type": f["semantic_type"], "occurs": f["occurs"],
                    "redefines": f["redefines"], "offset": None, "byte_length": None})
    return out


def unit_facts(us: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {u["unit_id"]: u for u in us}
