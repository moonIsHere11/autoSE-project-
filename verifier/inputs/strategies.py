"""Test-input generation from the DATA DIVISION (spec section 6, T1).

The generator produces *models* (field → value text per channel); `materialise` turns a model into
exact bytes (stdin lines, input files). Every case records its strategy and seed. Boundary and
literal-seeded cases are deterministic; the random part depends on the effective seed, which rotates
per repair iteration.
"""

from __future__ import annotations

import copy
import hashlib
import random
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from verifier.cobol.analysis import AcceptSite, FileChannel, LiteralSeed
from verifier.cobol.datadiv import DataItem
from verifier.cobol.syntax import Program
from verifier.inputs.bundle import CaseSpec, InputFile
from verifier.inputs.encode import canonical_text, encode_record, field_max, ulp

Model = dict[str, Any]


def minimal_text(value: Decimal) -> str:
    s = format(value.normalize(), "f")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    if s in ("-0", ""):
        s = "0"
    return s


@dataclass
class StdinSlot:
    site: AcceptSite
    block: int  # consecutive in-loop sites share a block and repeat together


@dataclass
class ProgramInputs:
    program: Program
    stdin: list[StdinSlot]
    files: list[FileChannel]
    args: list[AcceptSite]
    env: list[AcceptSite]
    seeds: list[LiteralSeed]
    uses_time: bool

    @staticmethod
    def build(program: Program, accepts: list[AcceptSite], files: list[FileChannel],
              seeds: list[LiteralSeed], uses_time: bool) -> ProgramInputs:
        slots: list[StdinSlot] = []
        block = 0
        prev_loop = False
        for a in accepts:
            if a.source != "stdin":
                continue
            if not (a.in_loop and prev_loop):
                block += 1
            slots.append(StdinSlot(a, block))
            prev_loop = a.in_loop
        return ProgramInputs(
            program, slots, [f for f in files if f.is_input and f.fd is not None and f.path],
            [a for a in accepts if a.source in ("cmdline", "argument")],
            [a for a in accepts if a.source == "env"], seeds, uses_time,
        )

    def input_field_names(self) -> set[str]:
        names = {s.site.target for s in self.stdin} | {a.target for a in self.args + self.env}
        for f in self.files:
            assert f.fd is not None
            for rec in f.fd.records[:1]:
                names |= {i.name for i in rec.walk() if i.is_elementary and not i.is_filler}
        return names


# ---------------------------------------------------------------------------------------------
# per-field value sets
# ---------------------------------------------------------------------------------------------
def numeric_boundaries(item: DataItem, overlong: bool) -> list[tuple[str, str]]:
    """(label, value text) pairs."""
    pic = item.pic
    assert pic is not None and pic.category == "numeric"
    mx, u = field_max(pic), ulp(pic)
    vals: list[tuple[str, Decimal | str]] = [("zero", Decimal(0)), ("ulp", u), ("max", mx), ("max-ulp", mx - u)]
    if pic.integer_digits > 0 and Decimal(1) <= mx:
        vals.append(("one", Decimal(1)))
    if pic.scale > 0:
        vals.append(("all-nines-scale", Decimal("0." + "9" * pic.scale)))
        vals.append(("half-ulp-5", u * 5 if pic.scale >= 1 else Decimal(5)))
        vals.append(("round-5", (Decimal(2) + u * 5) if mx >= 3 else u * 5))
    else:
        vals.append(("five", Decimal(5) if mx >= 5 else mx))
    if pic.signed:
        vals += [("neg-ulp", -u), ("neg-max", -mx), ("neg-one", Decimal(-1))]
        if pic.scale > 0:
            vals.append(("neg-round-5", -((Decimal(2) + u * 5) if mx >= 3 else u * 5)))
        vals.append(("negative-zero", "-0"))
    if overlong:
        vals.append(("one-past-max", mx + u))
        if pic.signed:
            vals.append(("one-past-min", -(mx + u)))
    out = []
    for label, v in vals:
        text = v if isinstance(v, str) else minimal_text(v)
        out.append((label, text))
    return _dedup(out)


def alnum_boundaries(item: DataItem, overlong: bool) -> list[tuple[str, str]]:
    n = max(1, item.unit_size)
    base = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789" * (n // 36 + 2)
    vals = [("empty", ""), ("one-char", "A"), ("full", base[:n]), ("mixed-case", "aBcDeFgHiJ" * (n // 10 + 1))]
    vals[-1] = ("mixed-case", vals[-1][1][:n])
    vals.append(("digits", ("0123456789" * (n // 10 + 1))[:n]))
    vals.append(("leading-spaces", ("  " + base)[:n]))
    if overlong:
        vals.append(("overlong", base[: n + 3]))
    for c in item.conditions:
        for lo, _hi in c.values_88:
            if lo.kind == "str":
                vals.append((f"88:{c.name}", lo.text))
    return _dedup(vals)


def _dedup(vals: list[tuple[str, str]]) -> list[tuple[str, str]]:
    seen: set[str] = set()
    out = []
    for label, v in vals:
        if v in seen:
            continue
        seen.add(v)
        out.append((label, v))
    return out


def literal_values(item: DataItem, seeds: list[LiteralSeed], name: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    pic = item.pic
    if pic is None:
        return out
    for s in seeds:
        if s.field != name:
            continue
        if s.kind == "num" and pic.category == "numeric":
            v = Decimal(s.value)
            u = ulp(pic)
            for label, x in (("lit", v), ("lit-1", v - 1), ("lit+1", v + 1), ("lit-ulp", v - u), ("lit+ulp", v + u)):
                if x < 0 and not pic.signed:
                    continue
                out.append((f"{label}:{s.value}", minimal_text(x)))
        elif s.kind == "str" and pic.category != "numeric":
            out.append((f"lit:{s.value!r}", s.value))
    return _dedup(out)


def random_value(item: DataItem, rng: random.Random) -> str:
    pic = item.pic
    if pic is None or pic.category != "numeric":
        n = item.unit_size
        k = rng.randint(0, n)
        alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789 -.,"
        return "".join(rng.choice(alphabet) for _ in range(k)).rstrip() if k else ""
    # log-uniform magnitude so small and large values both appear
    digits = rng.randint(0, pic.digits)
    n = rng.randint(0, 10**digits - 1) if digits else 0
    if pic.signed and rng.random() < 0.4:
        n = -n
    return minimal_text(Decimal(n).scaleb(-pic.scale))


def default_value(item: DataItem) -> str:
    pic = item.pic
    if pic is None or pic.category != "numeric":
        return "A"
    return minimal_text(Decimal(1)) if field_max(pic) >= 1 else minimal_text(ulp(pic))


# ---------------------------------------------------------------------------------------------
class Generator:
    def __init__(self, pi: ProgramInputs, seed: int, mode: str, *, case_cap: int, random_n: int,
                 pairwise: bool, extra_lines: int, fake_time: str | None) -> None:
        self.pi = pi
        self.seed = seed
        mix = hashlib.sha256(f"{seed}:{pi.program.program_id}".encode()).digest()
        self.rng = random.Random(int.from_bytes(mix[:8], "big"))
        self.mode = mode
        self.case_cap = case_cap
        self.random_n = random_n
        self.pairwise = pairwise
        self.extra_lines = extra_lines
        self.fake_time = fake_time if pi.uses_time else None

    # ---- models -------------------------------------------------------------------------------
    def _record_item(self, fc: FileChannel) -> DataItem:
        assert fc.fd is not None
        return fc.fd.records[0]

    def _record_fields(self, fc: FileChannel) -> list[DataItem]:
        rec = self._record_item(fc)
        items = [i for i in rec.walk() if i.is_elementary and not i.is_filler and not i.redefines
                 and i.pic is not None]
        return items or [rec]

    def base_model(self) -> Model:
        stdin = []
        for slot in self.pi.stdin:
            item = slot.site.item
            stdin.append({"field": slot.site.target, "text": default_value(item) if item else "1"})
        files = {}
        for fc in self.pi.files:
            assert fc.path is not None
            rec = {i.name: default_value(i) for i in self._record_fields(fc)}
            files[fc.path] = {"select": fc.select.name, "records": [rec], "trim": False, "tail": "",
                              "final_newline": True}
        args = [default_value(a.item) if a.item else "1" for a in self.pi.args]
        env = {a.env_name: default_value(a.item) if a.item else "1" for a in self.pi.env if a.env_name}
        return {"stdin": stdin, "files": files, "args": args, "env": env}

    def _slots(self) -> list[tuple[str, DataItem, Any]]:
        """Every input field position: ('stdin', item, index) / ('file', item, (path, field)) / ..."""
        out: list[tuple[str, DataItem, Any]] = []
        for i, slot in enumerate(self.pi.stdin):
            if slot.site.item is not None and slot.site.item.pic is not None:
                out.append(("stdin", slot.site.item, i))
        for fc in self.pi.files:
            for item in self._record_fields(fc):
                out.append(("file", item, (fc.path, item.name)))
        for i, a in enumerate(self.pi.args):
            if a.item is not None and a.item.pic is not None:
                out.append(("arg", a.item, i))
        return out

    @staticmethod
    def _set(model: Model, kind: str, where: Any, value: str) -> None:
        if kind == "stdin":
            model["stdin"][where]["text"] = value
        elif kind == "file":
            path, name = where
            for rec in model["files"][path]["records"]:
                rec[name] = value
        elif kind == "arg":
            model["args"][where] = value

    def _values_for(self, kind: str, item: DataItem) -> list[tuple[str, str]]:
        overlong = kind in ("stdin", "arg")
        vals = numeric_boundaries(item, overlong) if item.is_numeric else alnum_boundaries(item, overlong)
        vals += literal_values(item, self.pi.seeds, item.name)
        return _dedup(vals)

    def _loop_blocks(self) -> dict[int, list[int]]:
        blocks: dict[int, list[int]] = {}
        for i, slot in enumerate(self.pi.stdin):
            if slot.site.in_loop:
                blocks.setdefault(slot.block, []).append(i)
        return blocks

    def _with_repeats(self, model: Model, repeats: dict[int, int], rng: random.Random | None) -> Model:
        """Repeat each in-loop block `repeats[block]` extra times (values random or copied)."""
        if not repeats:
            return model
        m = copy.deepcopy(model)
        out: list[dict[str, str]] = []
        i = 0
        stdin = m["stdin"]
        while i < len(stdin):
            slot = self.pi.stdin[i] if i < len(self.pi.stdin) else None
            if slot is not None and slot.site.in_loop and slot.block in repeats:
                idxs = [j for j in range(i, len(self.pi.stdin)) if self.pi.stdin[j].block == slot.block]
                block_lines = [stdin[j] for j in idxs]
                out.extend(block_lines)
                for _ in range(repeats[slot.block]):
                    for j in idxs:
                        item = self.pi.stdin[j].site.item
                        text = random_value(item, rng) if (rng is not None and item is not None) else stdin[j]["text"]
                        out.append({"field": stdin[j]["field"], "text": text})
                i = idxs[-1] + 1
            else:
                out.append(stdin[i])
                i += 1
        m["stdin"] = out
        return m

    def generate(self) -> list[tuple[str, Model]]:
        base = self.base_model()
        cases: list[tuple[str, Model]] = [("base", base)]
        slots = self._slots()
        per_slot: list[list[tuple[str, str]]] = []
        for kind, item, where in slots:
            vals = self._values_for(kind, item)
            per_slot.append(vals)
            for label, v in vals:
                m = copy.deepcopy(base)
                self._set(m, kind, where, v)
                cases.append((f"boundary:{item.name}={label}", m))
        # files: cardinalities and line-shape variants
        for fc in self.pi.files:
            path = fc.path
            variants: list[tuple[str, Callable[[dict[str, Any]], None] | None]] = [
                ("0-records", lambda f: f.update(records=[])),
                ("many-records", None),
                ("short-lines", lambda f: f.update(trim=True)),
                ("overlong-line", lambda f: f.update(tail="XYZ")),
                ("no-final-newline", lambda f: f.update(final_newline=False)),
            ]
            for label, mutate in variants:
                if fc.select.organization != "LINE SEQUENTIAL" and label in ("short-lines", "overlong-line", "no-final-newline"):
                    continue
                m = copy.deepcopy(base)
                f = m["files"][path]
                if mutate is None:
                    rng = random.Random(self.rng.random())
                    f["records"] = [{i.name: random_value(i, rng) for i in self._record_fields(fc)}
                                    for _ in range(rng.randint(5, 20))]
                else:
                    mutate(f)
                cases.append((f"file:{path}:{label}", m))
        # loops: fill in-loop ACCEPT blocks to several depths
        blocks = self._loop_blocks()
        for depth in (0, 2, 5, 25):
            if not blocks:
                break
            rng = random.Random(self.rng.random())
            cases.append((f"loop-depth:{depth}", self._with_repeats(base, dict.fromkeys(blocks, depth), rng)))
        # pairwise combinations of per-field values
        if self.pairwise and len(slots) >= 2:
            for k, combo in enumerate(pairwise(per_slot, self.rng, cap=max(20, self.case_cap // 3))):
                m = copy.deepcopy(base)
                for (kind, _item, where), (_label, v) in zip(slots, combo, strict=True):
                    self._set(m, kind, where, v)
                cases.append((f"pairwise:{k}", m))
        # seeded uniform random
        for k in range(self.random_n):
            rng = random.Random(self.rng.random())
            m = copy.deepcopy(base)
            for kind, item, where in slots:
                if kind == "file":
                    continue
                self._set(m, kind, where, random_value(item, rng))
            for fc in self.pi.files:
                m["files"][fc.path]["records"] = [
                    {i.name: random_value(i, rng) for i in self._record_fields(fc)}
                    for _ in range(rng.randint(0, 8))
                ]
            if blocks:
                m = self._with_repeats(m, {b: rng.randint(0, self.extra_lines + 3) for b in blocks}, rng)
            cases.append((f"random:{k}", m))
        # deterministic priority: base, boundaries, files, loops, pairwise, random — then cap
        return cases[: self.case_cap]

    # ---- bytes --------------------------------------------------------------------------------
    def materialise(self, model: Model, strategy: str) -> CaseSpec:
        lines = [e["text"] for e in model.get("stdin", [])]
        stdin = ("\n".join(lines) + "\n").encode("latin-1", errors="replace") if lines else b""
        files: list[InputFile] = []
        for fc in self.pi.files:
            spec = model.get("files", {}).get(fc.path)
            if spec is None:
                continue
            rec_item = self._record_item(fc)
            recs = [encode_record(rec_item, r) for r in spec["records"]]
            if fc.select.organization == "LINE SEQUENTIAL":
                out_lines = []
                for r in recs:
                    if spec.get("trim"):
                        r = r.rstrip(b" ")
                    out_lines.append(r + spec.get("tail", "").encode("latin-1"))
                data = b"\n".join(out_lines)
                if out_lines and spec.get("final_newline", True):
                    data += b"\n"
            else:
                data = b"".join(recs)
            assert fc.path is not None
            files.append(InputFile(fc.path, data))
        return CaseSpec(
            program=self.pi.program.program_id, stdin=stdin, args=list(model.get("args", [])),
            env=dict(model.get("env", {})), fake_time=self.fake_time, files_in=files,
            strategy=strategy, seed=self.seed, model=model,
        )


# ---------------------------------------------------------------------------------------------
def pairwise(value_sets: list[list[tuple[str, str]]], rng: random.Random, cap: int) -> list[list[tuple[str, str]]]:
    """Greedy all-pairs covering array (deterministic given rng)."""
    sets = [vs for vs in value_sets]
    k = len(sets)
    uncovered = {(i, a, j, b) for i in range(k) for j in range(i + 1, k)
                 for a in range(len(sets[i])) for b in range(len(sets[j]))}
    tests: list[list[tuple[str, str]]] = []
    while uncovered and len(tests) < cap:
        i0, a0, j0, b0 = min(uncovered)
        choice: list[int | None] = [None] * k
        choice[i0], choice[j0] = a0, b0
        order = [x for x in range(k) if choice[x] is None]
        rng.shuffle(order)
        for f in order:
            best, best_gain = 0, -1
            for v in range(len(sets[f])):
                gain = 0
                for g in range(k):
                    cg = choice[g]
                    if cg is None or g == f:
                        continue
                    key = (g, cg, f, v) if g < f else (f, v, g, cg)
                    if key in uncovered:
                        gain += 1
                if gain > best_gain:
                    best, best_gain = v, gain
            choice[f] = best
        final = [c if c is not None else 0 for c in choice]
        for i in range(k):
            for j in range(i + 1, k):
                uncovered.discard((i, final[i], j, final[j]))
        tests.append([sets[f][final[f]] for f in range(k)])
    return tests


# ---------------------------------------------------------------------------------------------
# shrinking candidates
# ---------------------------------------------------------------------------------------------
def shrink_candidates(model: Model, n_sites: int) -> list[tuple[str, Model]]:
    """Simpler variants of a model, simplest first (used by delta debugging)."""
    out: list[tuple[str, Model]] = []
    stdin = model.get("stdin", [])
    if len(stdin) > n_sites:
        m = copy.deepcopy(model)
        m["stdin"] = stdin[:n_sites]
        out.append(("drop-extra-lines", m))
        m = copy.deepcopy(model)
        m["stdin"] = stdin[:-1]
        out.append(("drop-last-line", m))
    for path, spec in model.get("files", {}).items():
        recs = spec.get("records", [])
        if len(recs) > 1:
            for k in range(len(recs)):
                m = copy.deepcopy(model)
                del m["files"][path]["records"][k]
                out.append((f"drop-record:{path}:{k}", m))
                if len(out) > 12:
                    break
        for k, rec in enumerate(recs[:4]):
            for name, v in rec.items():
                for simpler in _simpler(v):
                    m = copy.deepcopy(model)
                    m["files"][path]["records"][k][name] = simpler
                    out.append((f"simplify:{path}:{k}:{name}", m))
    for i, e in enumerate(stdin):
        for simpler in _simpler(e["text"]):
            m = copy.deepcopy(model)
            m["stdin"][i]["text"] = simpler
            out.append((f"simplify:stdin:{i}:{e['field']}", m))
    return out


def _simpler(text: str) -> list[str]:
    t = text.strip()
    try:
        d = Decimal(t)
        is_num = bool(t) and t.lstrip("-").replace(".", "", 1).isdigit()
    except Exception:  # any non-number is treated as text
        is_num = False
        d = Decimal(0)
    out: list[str] = []
    if is_num:
        if d != 0:
            out.append("0")
            if "." in t:
                out.append(minimal_text(d.to_integral_value(rounding="ROUND_DOWN")))
            half = (d / 2).quantize(Decimal(1).scaleb(-(len(t.split(".")[1]) if "." in t else 0)), rounding="ROUND_DOWN")
            if half != 0 and half != d:
                out.append(minimal_text(half))
            if d < 0:
                out.append(minimal_text(-d))
    else:
        if text:
            out.append("")
            if len(text) > 1:
                out.append(text[: len(text) // 2])
    return [o for o in out if o != text]


def canonical(value: Decimal, scale: int) -> str:
    return canonical_text(value, scale)
