"""Oracle O4 (model-based): the verifier's validated interpreter, `interp.run_paragraph`, on random
states drawn from each field's PIC domain. It shares the front end with Phase 0, so E5 results are
reported separately and are never the only evidence for a claim (ADR-0005).

E5 checks, per paragraph p, with R/W = KB reads/writes closed over the units p can reach (PERFORM,
GO TO, and fall-through after a GO TO), because run_paragraph executes everything p performs:
* write soundness: every elementary item whose bytes change is in W;
* read soundness: perturbing an item f outside R leaves stdout, flow, RETURN-CODE and every other
  item unchanged, and leaves f either at its base output or at its perturbed input.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from phase0.stages.storage import byte_ranges, overlaps, storage_key
from verifier.cobol import ir as I
from verifier.cobol.datadiv import DataItem
from verifier.cobol.interp import CobolRuntimeError, InterpUnsupported, ParagraphResult, run_paragraph
from verifier.inputs.encode import EncodeError, encode_elementary
from verifier.inputs.strategies import random_value

STATEMENT_LIMIT = 20_000
STATES = 3
PERTURB = 10
SEED = 20261119


def record_key(r: DataItem) -> str:
    """The interpreter's state key for a record (`interp._record_key`)."""
    if r.name != "FILLER":
        return r.name
    return f"FILLER@{r.line}"


@dataclass
class Elementary:
    item: DataItem
    root: DataItem
    field_id: str
    ranges: list[tuple[int, int]]


def roots(prog_ir: I.IrProgram) -> list[DataItem]:
    p = prog_ir.program
    return [r for fd in p.fds for r in fd.records] + p.working_storage + p.local_storage


def elementaries(prog_ir: I.IrProgram, id_of: Callable[[DataItem], str | None]) -> list[Elementary]:
    out: list[Elementary] = []
    for root in roots(prog_ir):
        for item in root.walk():
            fid = id_of(item)
            if item.is_elementary and fid is not None and "FILLER#" not in fid and item.pic is not None:
                out.append(Elementary(item, root, fid, byte_ranges(item)))
    return out


def random_state(prog_ir: I.IrProgram, items: list[Elementary], rng: random.Random) -> dict[str, bytes]:
    """One buffer per storage area (a 01 and its REDEFINES, an FD's records), given to every record
    in it: the interpreter shares that storage, so separate buffers would overwrite each other."""
    prog = prog_ir.program
    areas: dict[str, bytearray] = {}
    for r in roots(prog_ir):
        key = storage_key(prog, r)
        size = max(len(areas.get(key, b"")), r.size)
        areas[key] = bytearray(bytes(areas.get(key, b"")).ljust(size, b" "))
    # numeric items last: an alphanumeric REDEFINES filled afterwards would put invalid bytes into a
    # numeric item, and reading invalid data rewrites it (GnuCOBOL fixes a SIGN SEPARATE byte)
    for e in sorted(items, key=is_numeric):
        fill(areas[storage_key(prog, e.root)], e, rng)
    return {record_key(r): bytes(areas[storage_key(prog, r)][: r.size]) for r in roots(prog_ir)}


def fill(buf: bytearray, e: Elementary, rng: random.Random) -> None:
    for lo, hi in e.ranges:
        try:
            data = encode_elementary(e.item, random_value(e.item, rng))
        except EncodeError:
            data = b" " * (hi - lo)
        buf[lo:hi] = data[: hi - lo].ljust(hi - lo, b" ")


def slice_of(state: dict[str, bytes], e: Elementary) -> bytes:
    data = state.get(record_key(e.root), b"")
    return b"".join(data[lo:hi] for lo, hi in e.ranges)


def is_numeric(e: Elementary) -> bool:
    return e.item.pic is not None and e.item.pic.category == "numeric"


def overlays_numeric(prog_ir: I.IrProgram, e: Elementary, items: list[Elementary]) -> bool:
    """An alphanumeric item sharing bytes with a numeric one: perturbing it makes that numeric item
    invalid data, which is outside what the KB describes."""
    return not is_numeric(e) and any(is_numeric(g) and shares_storage(prog_ir, e, g) for g in items if g is not e)


def shares_storage(prog_ir: I.IrProgram, a: Elementary, b: Elementary) -> bool:
    if storage_key(prog_ir.program, a.root) != storage_key(prog_ir.program, b.root):
        return False
    return overlaps(a.ranges, b.ranges)


@dataclass
class E5Tally:
    paragraphs: int = 0
    runs: int = 0
    refused: dict[str, int] = field(default_factory=dict)
    write_checks: int = 0
    read_checks: int = 0
    write_violations: list[dict[str, Any]] = field(default_factory=list)
    read_violations: list[dict[str, Any]] = field(default_factory=list)
    declared_writes: int = 0
    observed_writes: int = 0

    def refuse(self, reason: str) -> None:
        key = reason.split(":")[0][:60]
        self.refused[key] = self.refused.get(key, 0) + 1


def run_safely(prog_ir: I.IrProgram, name: str, state: dict[str, bytes], tally: E5Tally) -> ParagraphResult | None:
    tally.runs += 1
    try:
        return run_paragraph(prog_ir, name, state=state, statement_limit=STATEMENT_LIMIT)
    except (InterpUnsupported, CobolRuntimeError, EncodeError) as exc:
        tally.refuse(f"{type(exc).__name__}: {exc}")
        return None


@dataclass
class Facts:
    """One analyser's view of a paragraph, closed over what run_paragraph executes."""

    reads: set[str]
    writes: set[str]
    return_code: str  # field id of RETURN-CODE in this analyser's naming


def check_paragraph(prog_ir: I.IrProgram, name: str, items: list[Elementary], facts: Facts,
                    tally: E5Tally, program: str, label: str) -> None:
    reads, writes = facts.reads, facts.writes
    rng = random.Random(f"{SEED}:{program}:{name}")
    tally.paragraphs += 1
    observed: set[str] = set()
    for _ in range(STATES):
        state = random_state(prog_ir, items, rng)
        base = run_safely(prog_ir, name, state, tally)
        if base is None:
            continue
        changed = {e.field_id for e in items if slice_of(base.state, e) != slice_of(state, e)}
        if base.return_code != 0:
            changed.add(facts.return_code)
        observed |= changed
        tally.write_checks += 1
        for fid in sorted(changed - writes):
            tally.write_violations.append({"metric": "E5", "check": "write", "source": label, "program": program,
                                           "unit": name, "field": fid})
        candidates = [e for e in items if e.field_id not in reads and not overlays_numeric(prog_ir, e, items)]
        for e in rng.sample(candidates, min(PERTURB, len(candidates))):
            perturb(prog_ir, name, items, state, base, e, rng, tally, program, label)
    tally.declared_writes += len(writes & {e.field_id for e in items})
    tally.observed_writes += len(observed & writes)


def perturb(prog_ir: I.IrProgram, name: str, items: list[Elementary], state: dict[str, bytes], base: ParagraphResult,
            e: Elementary, rng: random.Random, tally: E5Tally, program: str, label: str) -> None:
    buf = bytearray(state[record_key(e.root)])
    fill(buf, e, rng)
    alt = dict(state)
    key = storage_key(prog_ir.program, e.root)
    for r in roots(prog_ir):
        if storage_key(prog_ir.program, r) == key:
            alt[record_key(r)] = bytes(buf[: r.size]).ljust(r.size, b" ")
    if slice_of(alt, e) == slice_of(state, e):
        return
    res = run_safely(prog_ir, name, alt, tally)
    if res is None:
        return
    tally.read_checks += 1
    diffs: list[str] = []
    if res.stdout != base.stdout:
        diffs.append("stdout")
    if res.flow != base.flow or res.return_code != base.return_code:
        diffs.append("flow/RETURN-CODE")
    for g in items:
        out = slice_of(res.state, g)
        if g is e or shares_storage(prog_ir, g, e):
            # the perturbed bytes themselves may pass through unchanged
            if out not in (slice_of(base.state, g), slice_of(alt, g)):
                diffs.append(g.field_id)
        elif out != slice_of(base.state, g):
            diffs.append(g.field_id)
    if diffs:
        tally.read_violations.append({"metric": "E5", "check": "read", "source": label, "program": program,
                                      "unit": name, "perturbed": e.field_id, "changed": diffs[:6]})
