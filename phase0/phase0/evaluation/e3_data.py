"""E3: data dictionary against O1 (listing + probe) and O3 (manifest.java.json declared types)."""

from __future__ import annotations

import difflib
import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from phase0.evaluation.o1 import ListingRow, ProbeResult, shown_type

# GnuCOBOL's listing TYPE is the class of the item: numeric-edited items are NUMERIC there, while
# datadiv (and the contract's semantic_type) treat them as character storage; compare categories.
LISTING_CATEGORY = {"NUMERIC": {"numeric", "numeric-edited"}, "GROUP": {"group"},
                    "ALPHANUMERIC": {"alphanumeric", "alphanumeric-edited"}, "ALPHABETIC": {"alphabetic"}}
USAGE_SYNONYMS = {"PACKED-DECIMAL": "COMP-3", "COMPUTATIONAL-3": "COMP-3", "BINARY": "COMP", "COMPUTATIONAL": "COMP",
                  "COMPUTATIONAL-5": "COMP-5"}
NUMERIC_KINDS = {"decimal", "binary", "packed"}


@dataclass
class Tally:
    compared: Counter[str] = field(default_factory=Counter)
    matched: Counter[str] = field(default_factory=Counter)
    failures: list[dict[str, Any]] = field(default_factory=list)

    def check(self, attr: str, program: str, fid: str, kb: object, oracle: object, oracle_name: str, repro: str) -> None:
        self.compared[attr] += 1
        if kb == oracle:
            self.matched[attr] += 1
            return
        self.failures.append({"metric": "E3", "attribute": attr, "program": program, "field_id": fid, "kb": kb,
                              "oracle": oracle, "oracle_name": oracle_name, "repro": repro})

    def rates(self) -> dict[str, dict[str, float | int]]:
        return {a: {"compared": self.compared[a], "matched": self.matched[a],
                    "rate": round(self.matched[a] / self.compared[a], 4)} for a in sorted(self.compared)}


def kb_rows(fields: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [f for f in fields if f["name"] != "RETURN-CODE" and f["level"] not in (66, 88)]


def listing_rows(rows: list[ListingRow]) -> list[ListingRow]:
    return [r for r in rows if r.level is not None and r.type != "CONDITIONAL" and r.name != "RETURN-CODE"]


def align(kb: list[dict[str, Any]], rows: list[ListingRow]) -> tuple[list[tuple[dict[str, Any], ListingRow]], int, int]:
    """Pairs aligned on (level, name) in document order; also counts of unmatched KB and listing items."""
    a = [(f["level"], f["name"].split("#")[0]) for f in kb]
    b = [(r.level, r.name) for r in rows]
    sm = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
    pairs: list[tuple[dict[str, Any], ListingRow]] = []
    for block in sm.get_matching_blocks():
        for k in range(block.size):
            pairs.append((kb[block.a + k], rows[block.b + k]))
    return pairs, len(kb) - len(pairs), len(rows) - len(pairs)


def category_matches(f: dict[str, Any], row: ListingRow) -> bool:
    return f["category"] in LISTING_CATEGORY.get(row.type, {row.type.lower()})


def listing_size(f: dict[str, Any], row: ListingRow) -> tuple[int | None, int | None]:
    """(KB value, listing SIZE). The listing prints a group OCCURS item's total size and an
    elementary OCCURS item's per-occurrence size (observed on OCCURS.cbl)."""
    kb = f["byte_length"]
    if f["semantic_type"]["kind"] == "group" and f["occurs"]:
        kb = kb * f["occurs"]
    return kb, row.size


def score_listing(t: Tally, program: str, fields: list[dict[str, Any]], rows: list[ListingRow], repro: str) -> dict[str, int]:
    pairs, kb_only, lst_only = align(kb_rows(fields), listing_rows(rows))
    by_id = {f["field_id"]: f for f in fields}
    for f, row in pairs:
        fid = f["field_id"]
        kb_size, lst_size = listing_size(f, row)
        t.check("byte_length(listing)", program, fid, kb_size, lst_size, "cobc listing", repro)
        t.check("category(listing)", program, fid, True, category_matches(f, row), f"cobc listing TYPE {row.type}", repro)
        t.check("occurs(listing)", program, fid, f["occurs"], row.occurs, "cobc listing", repro)
        red: str | None = None
        if f["redefines"]:
            red = by_id[f["redefines"]]["name"]
        t.check("redefines(listing)", program, fid, red, row.redefines, "cobc listing", repro)
    return {"aligned": len(pairs), "kb_only": kb_only, "listing_only": lst_only}


def score_probe(t: Tally, program: str, fields: list[dict[str, Any]], probe: ProbeResult, repro: str) -> None:
    by_id = {f["field_id"]: f for f in fields}
    for fid, (offset, length) in sorted(probe.offsets.items()):
        f = by_id[fid]
        t.check("offset(probe)", program, fid, f["offset"], offset, "GnuCOBOL probe", repro)
        t.check("byte_length(probe)", program, fid, f["byte_length"], length, "GnuCOBOL probe", repro)
    for fid, text in sorted(probe.shown.items()):
        st = by_id[fid]["semantic_type"]
        signed, digits, scale = shown_type(text)
        t.check("signed(probe)", program, fid, st["signed"], signed, "GnuCOBOL probe", repro)
        if "P" not in (by_id[fid]["pic"] or "").upper():  # DISPLAY prints P positions as digits
            t.check("digits(probe)", program, fid, st["digits"], digits, "GnuCOBOL probe", repro)
        t.check("scale(probe)", program, fid, st["scale"], scale, "GnuCOBOL probe", repro)


def score_manifest(t: Tally, program: str, fields: list[dict[str, Any]], manifest: Path, repro: str) -> None:
    """Declared types written by the corpus authors (O3). Names are unqualified in the manifest."""
    data = json.loads(manifest.read_text("utf-8"))
    by_name: dict[str, list[dict[str, Any]]] = {}
    for f in fields:
        by_name.setdefault(f["name"], []).append(f)
    for prog in data["programs"]:
        for entry in prog.get("fields", []):
            cands = by_name.get(entry["cobol"].upper(), [])
            if len(cands) != 1:
                t.check("name(manifest)", program, entry["cobol"], len(cands), 1, "manifest.java.json", repro)
                continue
            f = cands[0]
            d = entry["declared"]
            st = f["semantic_type"]
            if d["kind"] in NUMERIC_KINDS:
                t.check("kind(manifest)", program, f["field_id"], st["kind"], "decimal", "manifest.java.json", repro)
                t.check("digits(manifest)", program, f["field_id"], st["digits"], d["digits"], "manifest.java.json", repro)
                t.check("scale(manifest)", program, f["field_id"], st["scale"], d["scale"], "manifest.java.json", repro)
                t.check("signed(manifest)", program, f["field_id"], st["signed"], d["signed"], "manifest.java.json", repro)
                if "usage" in d:
                    usage = USAGE_SYNONYMS.get(d["usage"], d["usage"])
                    t.check("usage(manifest)", program, f["field_id"], f["usage"], usage, "manifest.java.json", repro)
            else:
                kind = "group"
                if d["kind"] in ("alnum", "alpha"):
                    kind = "alphanumeric"
                t.check("kind(manifest)", program, f["field_id"], st["kind"], kind, "manifest.java.json", repro)
                if "length" in d:
                    t.check("length(manifest)", program, f["field_id"], st["length"], d["length"], "manifest.java.json", repro)
