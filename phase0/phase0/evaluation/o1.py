"""Oracle O1: GnuCOBOL at compile time, independent of Phase 0's parser.

* Listing: `cobc -fsyntax-only -t LIST -ftsymbols` prints SIZE, TYPE, LEVEL, NAME, PICTURE,
  OCCURS and REDEFINES for every data item, as the compiler laid it out.
* Probe: a generated program with the original DATA DIVISION and a PROCEDURE DIVISION that, for
  each item, prints its offset (pointer difference to its 01 record), FUNCTION BYTE-LENGTH, and
  the DISPLAY of `MOVE -1` (sign, digit count and scale as GnuCOBOL formats them).

The probe only uses the KB to know which names to ask about; every number comes from GnuCOBOL.
"""

from __future__ import annotations

import re
import shlex
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from verifier.sandbox.docker_runner import Mount

from phase0.toolbox import Toolbox

ROW = re.compile(r"^(\d{5}|     ) (\S[\w -]*?)\s{2,}(\d\d|  )\s{3}(\S.*)$")
PROBE_PREFIX = "PHASE0-"


@dataclass
class ListingRow:
    size: int | None
    type: str
    level: int | None
    name: str
    redefines: str | None
    picture: str | None
    occurs: int | None
    section: str


def parse_listing(text: str) -> list[ListingRow]:
    rows: list[ListingRow] = []
    in_table = False
    section = "FILE"
    for line in text.splitlines():
        if line.startswith("SIZE  TYPE"):
            in_table = True
            continue
        if not in_table:
            continue
        stripped = line.strip()
        if stripped.endswith("SECTION"):
            section = stripped.replace(" SECTION", "")
            continue
        m = ROW.match(line)
        if m is None:
            continue
        rows.append(listing_row(m, section))
    return rows


def listing_row(m: re.Match[str], section: str) -> ListingRow:
    size_text, type_text, level_text, rest = m.groups()
    parts = re.split(r"\s{2,}", rest.strip())
    name_part = parts[0]
    pic_part: str | None = None
    if len(parts) > 1:
        pic_part = parts[1]
    redefines = None
    rm = re.search(r",\s*REDEFINES\s+(\S+)", name_part + " " + (pic_part or ""))
    if rm:
        redefines = rm.group(1).upper()
    name = name_part.split(",")[0].strip().upper()
    occurs = None
    picture = None
    if pic_part is not None:
        om = re.search(r"OCCURS\s+(\d+)", pic_part)
        if om:
            occurs = int(om.group(1))
        pic_text = re.sub(r",?\s*(OCCURS\s+\d+|REDEFINES\s+\S+)", "", pic_part).strip(" ,")
        picture = pic_text or None
    size: int | None = None
    if size_text.strip():
        size = int(size_text)
    level: int | None = None
    if level_text.strip():
        level = int(level_text)
    return ListingRow(size, type_text.strip(), level, name, redefines, picture, occurs, section)


# ---- probe ------------------------------------------------------------------------------------
@dataclass
class ProbeItem:
    key: int
    field_id: str
    ref: str  # qualified COBOL reference with (1, ...) subscripts
    root_ref: str
    numeric: bool


@dataclass
class ProbeResult:
    offsets: dict[str, tuple[int, int]] = field(default_factory=dict)  # field_id -> (offset, byte length)
    shown: dict[str, str] = field(default_factory=dict)  # field_id -> DISPLAY of MOVE -1
    error: str | None = None


def qualified_ref(fields: dict[str, dict[str, Any]], fid: str) -> str:
    """`NAME OF PARENT OF ROOT (1, 1)`: FILLER ancestors cannot qualify and are skipped."""
    chain: list[dict[str, Any]] = []
    cur: str | None = fid
    while cur is not None:
        chain.append(fields[cur])
        cur = fields[cur]["parent"]
    names = [f["name"] for f in chain if not f["name"].startswith("FILLER")]
    dims = sum(1 for f in chain if f["occurs"])
    ref = " OF ".join(names)
    if dims:
        ref += " (" + ", ".join("1" for _ in range(dims)) + ")"
    return ref


def probe_items(kb_fields: list[dict[str, Any]]) -> list[ProbeItem]:
    by_id = {f["field_id"]: f for f in kb_fields}
    out: list[ProbeItem] = []
    for f in kb_fields:
        if f["name"] is None or f["name"].startswith("FILLER") or f["field_id"].endswith("RETURN-CODE"):
            continue
        if f["section"] not in ("working-storage", "local-storage", "file") or f["level"] in (66, 88):
            continue
        root = f["field_id"]
        while by_id[root]["parent"] is not None:
            root = by_id[root]["parent"]
        numeric = (f["semantic_type"]["kind"] == "decimal" and f["usage"] != "COMP-5"
                   and (f["semantic_type"]["scale"] or 0) >= 0)
        out.append(ProbeItem(len(out), f["field_id"], qualified_ref(by_id, f["field_id"]),
                             qualified_ref(by_id, root).split(" (")[0], numeric))
    return out


def wrap(words: list[str], indent: str = "           ") -> list[str]:
    lines: list[str] = []
    cur = indent
    for w in words:
        if len(cur) + len(w) + 1 > 70 and cur.strip():
            lines.append(cur)
            cur = indent
        cur += " " + w
    lines.append(cur)
    return lines


def ref_words(ref: str) -> list[str]:
    return ref.replace("(", " ( ").replace(")", " ) ").replace(",", " , ").split()


def probe_source(original: str, items: list[ProbeItem]) -> str:
    """Original program up to PROCEDURE DIVISION, probe items in WORKING-STORAGE, probe procedure."""
    lines = original.splitlines()
    proc = next(i for i, ln in enumerate(lines) if re.search(r"^\s{0,11}\S*\s*PROCEDURE\s+DIVISION", ln[:72], re.I)
                and not (len(ln) > 6 and ln[6] in "*/"))
    head = lines[:proc]
    decls = [
        f"       01 {PROBE_PREFIX}P0 USAGE POINTER.",
        f"       01 {PROBE_PREFIX}N0 REDEFINES {PROBE_PREFIX}P0 PIC S9(18) COMP-5.",
        f"       01 {PROBE_PREFIX}P1 USAGE POINTER.",
        f"       01 {PROBE_PREFIX}N1 REDEFINES {PROBE_PREFIX}P1 PIC S9(18) COMP-5.",
        f"       01 {PROBE_PREFIX}OFF PIC 9(9).",
        f"       01 {PROBE_PREFIX}LEN PIC 9(9).",
    ]
    ws = next((i for i, ln in enumerate(head) if re.search(r"WORKING-STORAGE\s+SECTION", ln[:72], re.I)), None)
    if ws is None:
        head = [*head, "       WORKING-STORAGE SECTION.", *decls]
    else:
        head = head[: ws + 1] + decls + head[ws + 1 :]
    body = ["       PROCEDURE DIVISION."]
    for it in items:
        body += wrap(["SET", f"{PROBE_PREFIX}P0", "TO", "ADDRESS", "OF", *ref_words(it.root_ref)])
        body += wrap(["SET", f"{PROBE_PREFIX}P1", "TO", "ADDRESS", "OF", *ref_words(it.ref)])
        body += wrap(["COMPUTE", f"{PROBE_PREFIX}OFF", "=", f"{PROBE_PREFIX}N1", "-", f"{PROBE_PREFIX}N0"])
        body += wrap(["MOVE", "FUNCTION", "BYTE-LENGTH", "(", *ref_words(it.ref), ")", "TO", f"{PROBE_PREFIX}LEN"])
        body += wrap(["DISPLAY", f'"O|{it.key}|"', f"{PROBE_PREFIX}OFF", '"|"', f"{PROBE_PREFIX}LEN"])
    for it in items:
        if it.numeric:
            body += wrap(["MOVE", "-1", "TO", *ref_words(it.ref)])
            body += wrap(["DISPLAY", f'"V|{it.key}|"', *ref_words(it.ref)])
    body.append("           STOP RUN.")
    return "\n".join(head + body) + "\n"


def parse_probe_output(text: str, items: list[ProbeItem]) -> ProbeResult:
    res = ProbeResult()
    by_key = {it.key: it for it in items}
    for line in text.splitlines():
        parts = line.split("|")
        if len(parts) < 3 or not parts[1].isdigit() or int(parts[1]) not in by_key:
            continue
        fid = by_key[int(parts[1])].field_id
        if parts[0] == "O" and len(parts) == 4:
            res.offsets[fid] = (int(parts[2]), int(parts[3]))
        elif parts[0] == "V":
            res.shown[fid] = "|".join(parts[2:])
    return res


def shown_type(text: str) -> tuple[bool, int, int]:
    """(signed, digits, scale) from a numeric DISPLAY: sign char present, digit count, decimals."""
    t = text.strip()
    signed = t.startswith(("-", "+")) or t.endswith(("-", "+"))
    body = t.strip("+-")
    scale = 0
    if "." in body:
        scale = len(body.split(".", 1)[1])
    return signed, sum(ch.isdigit() for ch in body), scale


# ---- running in the toolchain image -------------------------------------------------------
@dataclass
class CompileJob:
    key: str
    source_rel: str  # program file under the source root
    flags: list[str]
    probe: str | None = None  # generated probe text
    items: list[ProbeItem] = field(default_factory=list)


@dataclass
class O1Outcome:
    listing: dict[str, list[ListingRow]] = field(default_factory=dict)
    probe: dict[str, ProbeResult] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)


def run_o1(toolbox: Toolbox, source_root: Path, jobs: list[CompileJob], include_dirs: list[str]) -> O1Outcome:
    out = O1Outcome()
    inc = " ".join(f"-I {shlex.quote(d)}" for d in include_dirs)
    with tempfile.TemporaryDirectory(prefix="phase0-o1-") as tmp_s:
        tmp = Path(tmp_s)
        script = ["set +e", "cd /src"]
        for i, job in enumerate(jobs):
            flags = " ".join(shlex.quote(f) for f in job.flags)
            src = shlex.quote(job.source_rel)
            d = shlex.quote(str(Path(job.source_rel).parent))
            script.append(f"cobc {flags} {inc} -I {d} -fsyntax-only -t /out/{i}.lst -ftsymbols -fno-ttimestamp {src} "
                          f"> /out/{i}.lerr 2>&1")
            if job.probe is not None:
                (tmp / f"{i}.cbl").write_text(job.probe, "latin-1")
                script.append(f"cobc -x {flags} {inc} -I {d} -o /out/{i}.exe /out/{i}.cbl > /out/{i}.perr 2>&1 "
                              f"&& (cd /out && ./{i}.exe > /out/{i}.out 2>> /out/{i}.perr)")
        (tmp / "o1.sh").write_text("\n".join(script) + "\n", "utf-8")
        toolbox.runner.run(["bash", "/out/o1.sh"], mounts=[Mount(source_root, "/src", True), Mount(tmp, "/out", False)],
                           timeout_s=1200)
        for i, job in enumerate(jobs):
            lst = tmp / f"{i}.lst"
            if lst.exists():
                out.listing[job.key] = parse_listing(lst.read_text("latin-1"))
            else:
                out.errors[job.key] = "listing: " + read(tmp / f"{i}.lerr")
            if job.probe is None:
                continue
            res_p = tmp / f"{i}.out"
            if res_p.exists():
                out.probe[job.key] = parse_probe_output(res_p.read_text("latin-1"), job.items)
            else:
                out.probe[job.key] = ProbeResult(error=read(tmp / f"{i}.perr"))
    return out


def read(p: Path) -> str:
    if not p.exists():
        return "(no output)"
    return p.read_text("latin-1")[-600:]
