"""E10 (optional): metamorphic robustness. Two source transformations that preserve meaning:
* rename: every data and procedure name is consistently renamed (outside literals and comments);
* free format: fixed-format source rewritten as free format with the same line count.
The KB of the transformed program must equal the original KB under the renaming."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from phase0.evaluation.datasets import Built, Program, build_program
from phase0.toolbox import Toolbox

WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]*")
LITERAL = re.compile(r"'[^']*'|\"[^\"]*\"")


def names_of(b: Built) -> list[str]:
    names = {f["name"] for f in b.kb("source/data_dictionary.json") if f["name"] and not f["name"].startswith("FILLER")}
    names |= {c["name"] for f in b.kb("source/data_dictionary.json") for c in f["condition_names"]}
    names |= {u["unit_id"] for u in b.kb("source/units.json") if u["kind"] != "program"}
    names.discard("RETURN-CODE")
    names.discard("(MAIN)")
    return sorted(names)


def rename_map(names: list[str]) -> dict[str, str]:
    """Same-length new names (at least 3 characters), so renamed lines keep the fixed-format margins."""
    out: dict[str, str] = {}
    for i, n in enumerate(names):
        width = max(len(n), 3) - 2
        out[n] = "Z" + base36(i).rjust(width, "0") + "Q"
    return out


def base36(n: int) -> str:
    digits = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    out = ""
    while True:
        n, r = divmod(n, 36)
        out = digits[r] + out
        if n == 0:
            return out


def rename_line(line: str, mapping: dict[str, str]) -> str:
    if len(line) > 6 and line[6] in "*/":
        return line
    head, body, tail = line[:7], line[7:72], line[72:]
    out, pos = [], 0
    for m in LITERAL.finditer(body):
        out.append(rename_words(body[pos:m.start()], mapping))
        out.append(m.group(0))
        pos = m.end()
    out.append(rename_words(body[pos:], mapping))
    new = "".join(out)
    if len(new) > 65:
        return ""  # signals: cannot rename within the fixed-format margin
    return head + new.ljust(len(body)) + tail


def rename_words(text: str, mapping: dict[str, str]) -> str:
    return WORD.sub(lambda m: mapping.get(m.group(0).upper(), m.group(0)), text)


def to_free(line: str) -> str:
    if len(line) > 6 and line[6] in "*/":
        return "*>" + line[7:]
    return line[7:72].rstrip()


def map_back(text: str, inverse: dict[str, str]) -> str:
    return re.sub(r"Z[0-9A-Z]*Q", lambda m: inverse.get(m.group(0), m.group(0)), text)


def facts(b: Built) -> dict[str, Any]:
    """What must not change: units (ids, kind, spans, reads, writes, control) and field layout."""
    units = [{k: u[k] for k in ("unit_id", "kind", "span", "reads", "writes", "performs", "goes_to", "falls_through_to",
                                "exits", "calls")} for u in b.kb("source/units.json")]
    fields = [{k: f[k] for k in ("field_id", "level", "offset", "byte_length", "semantic_type", "occurs", "redefines")}
              for f in b.kb("source/data_dictionary.json")]
    return {"units": units, "fields": fields}


def normalise(f: dict[str, Any]) -> dict[str, Any]:
    """Order-free comparison: KB lists are sorted by id, and renaming changes the sort order."""
    for u in f["units"]:
        for k in ("reads", "writes", "performs", "goes_to", "exits", "calls"):
            u[k] = sorted(u[k])
    f["units"].sort(key=lambda u: (u["span"]["start_line"], u["unit_id"]))
    f["fields"].sort(key=lambda x: x["field_id"])
    return f


def variant(b: Built, kind: str, work: Path, toolbox: Toolbox) -> tuple[bool | None, str]:
    src = (b.ws / "source" / b.program.entry).read_text("latin-1").splitlines()
    if any(len(ln) > 6 and ln[6] == "-" for ln in src):
        return None, "continuation lines"
    inverse: dict[str, str] = {}
    if kind == "rename":
        mapping = rename_map(names_of(b))
        inverse = {v: k for k, v in mapping.items()}
        lines = [rename_line(ln, mapping) for ln in src]
        if any(new == "" and old.strip() for new, old in zip(lines, src, strict=True)):
            return None, "renamed line exceeds column 72"
    else:
        lines = [to_free(ln) for ln in src]
    tmp = work / "e10" / kind / b.program.name
    tmp.mkdir(parents=True, exist_ok=True)
    path = tmp / b.program.entry
    path.write_text("\n".join(lines) + "\n", "latin-1")
    other = build_program(Program(b.program.dataset, b.program.name, [path], b.program.entry), work / "e10ws" / kind,
                          toolbox)
    got = normalise(json.loads(map_back(json.dumps(facts(other), sort_keys=True), inverse)))
    want = normalise(facts(b))
    if kind == "free":
        for u in got["units"] + want["units"]:
            u["span"].pop("file", None)
    return got == want, ""


def e10(built: list[Built], work: Path, toolbox: Toolbox) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    out: dict[str, Any] = {}
    failures: list[dict[str, Any]] = []
    for kind in ("rename", "free"):
        passed = failed = skipped = 0
        for b in built:
            ok, why = variant(b, kind, work, toolbox)
            if ok is None:
                skipped += 1
            elif ok:
                passed += 1
            else:
                failed += 1
                failures.append({"metric": "E10", "transformation": kind, "program": b.program.name,
                                 "repro": f"compare {work}/e10ws/{kind}/{b.program.dataset}/{b.program.name}/kb with {b.ws}/kb",
                                 "detail": why})
        out[kind] = {"pass": passed, "fail": failed, "skipped": skipped}
    return out, failures
