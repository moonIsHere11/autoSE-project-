"""`phase0 report`: architecture views and recovered decision records, generated from KB facts only.

Everything here is a deterministic function of the kb/source files, so `phase0 build` writes it
before computing kb_version and `phase0 report` regenerates identical bytes (and says so if not).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from phase0 import jsonio

EDGE_STYLE = {"perform": "-->", "perform-thru": "==>", "goto": "-.->", "fallthrough": "-.-", "call": "-->"}


def node(name: str) -> str:
    return "n_" + re.sub(r"[^A-Za-z0-9_]", "_", name)


def label(text: str) -> str:
    return text.replace('"', "'")


@dataclass
class Facts:
    units: list[dict[str, Any]]
    fields: list[dict[str, Any]]
    edges: list[dict[str, Any]]
    flow: dict[str, Any]
    inventory: list[dict[str, Any]]
    source: Path

    @classmethod
    def load(cls, kb: Path, source: Path) -> Facts:
        def read(rel: str) -> Any:
            return jsonio.read(kb / "source" / rel)

        return cls(read("units.json"), read("data_dictionary.json"), read("call_graph.json")["edges"],
                   read("data_flow.json"), read("inventory.json")["files"], source)

    def programs(self) -> list[str]:
        return sorted({u["program"] for u in self.units if u.get("program")})

    def units_of(self, program: str) -> list[dict[str, Any]]:
        return [u for u in self.units if u.get("program") == program]


# ---- views ----------------------------------------------------------------------------------------
def control_view(f: Facts, program: str) -> str:
    units = {u["unit_id"]: u for u in f.units_of(program)}
    lines = [f"# {program}: PERFORM / GO TO / fall-through / CALL graph", "",
             "Solid: PERFORM; thick: PERFORM THRU; dashed arrow: GO TO; dotted line: fall-through; "
             "hexagon: called program.", "", "```mermaid", "flowchart TD"]
    for uid, u in units.items():
        if u["kind"] != "program":
            lines.append(f'  {node(uid)}["{label(uid)}"]')
    seen: set[tuple[str, str, str]] = set()
    for e in f.edges:
        if e["src"] not in units or e["kind"] == "exit":
            continue
        key = (e["src"], e["dst"], e["kind"])
        if key in seen:
            continue
        seen.add(key)
        dst = node(e["dst"])
        if e["kind"] == "call":
            lines.append(f'  {dst}{{{{"{label(e["dst"])}"}}}}')
        lines.append(f"  {node(e['src'])} {EDGE_STYLE[e['kind']]} {dst}")
    lines += ["```", ""]
    return "\n".join(lines)


def data_view(f: Facts, program: str) -> str:
    units = {u["unit_id"] for u in f.units_of(program) if u["kind"] == "paragraph"}
    rows = ["| Field | Written by | Read by |", "| --- | --- | --- |"]
    for fl in f.flow["fields"]:
        writers = [w for w in fl["writers"] if w in units]
        readers = [r for r in fl["readers"] if r in units]
        if writers or readers:
            rows.append(f"| `{fl['field_id']}` | {', '.join(writers)} | {', '.join(readers)} |")
    crud = [c for c in f.flow["files"] if c["program"] == program]
    out = [f"# {program}: data view", "", "Field mutation table (paragraph units).", "", *rows, ""]
    if crud:
        out += ["## File CRUD matrix", "", "| File | Organization | ASSIGN | Unit | Operations |",
                "| --- | --- | --- | --- | --- |"]
        for c in crud:
            for unit, ops in sorted(c["units"].items()):
                out.append(f"| {c['file']} | {c['organization']} | {c['assign']} | {unit} | {''.join(ops)} |")
        out.append("")
    return "\n".join(out)


def batch_flow(f: Facts) -> str | None:
    """Job -> step -> program -> dataset, from the JCL scan (inventory)."""
    rows = [(e["path"], r) for e in f.inventory if e["kind"] == "jcl" for r in e["jcl_steps"]]
    if not rows:
        return None
    head = ["# Batch flow (JCL)", "", "Job -> step -> program; step -> dataset arrows point in the data direction "
            "(DISP=SHR/OLD read, NEW/MOD written).", "", "```mermaid", "flowchart LR"]
    lines: list[str] = []
    for path, r in rows:
        job = node(f"job_{r['job'] or path}")
        step = node(f"step_{r['job']}_{r['step']}")
        if r["kind"] == "exec":
            lines.append(f'  {job}(["{label(r["job"] or path)}"]) --> {step}["{label(r["step"])}"]')
            if "program" in r:
                lines.append(f'  {step} --> {node("pgm_" + r["program"])}[["{label(r["program"])}"]]')
        elif r["kind"] == "dd" and "dsn" in r and not r["dsn"].startswith("&"):
            ds = node("ds_" + r["dsn"])
            if writes_dataset(r.get("disp", "")):
                lines.append(f'  {step} --> {ds}[("{label(r["dsn"])}")]')
            else:
                lines.append(f'  {ds}[("{label(r["dsn"])}")] --> {step}')
    return "\n".join([*head, *dict.fromkeys(lines), "```", ""])


def writes_dataset(disp: str) -> bool:
    return disp.split(",")[0] in ("NEW", "MOD")


# ---- recovered decision records -------------------------------------------------------------------
@dataclass
class Record:
    title: str
    program: str
    decision: str
    evidence: list[str]
    consequences: str
    implication: str  # preserve | redesign | ask
    rationale: str = "unknown"
    lines: list[tuple[str, int]] = field(default_factory=list)


REASON = re.compile(r"\b(because|so that|in order to|to avoid|to prevent|since|reason|required by|due to|"
                    r"otherwise|must)\b", re.I)
BANNER = re.compile(r"^[*=\-\s]*$")
LEGAL = re.compile(r"copyright|licen[cs]e|all rights reserved|warrant", re.I)
CODE = re.compile(r"^(MOVE|DISPLAY|PERFORM|IF|COMPUTE|ADD|EXEC|CALL|GO TO)\b", re.I)


def comment_rationale(f: Facts, where: list[tuple[str, int]]) -> str:
    """A rationale only when a comment directly above the evidence states one; otherwise `unknown`."""
    for file, line in where[:3]:
        path = f.source / file
        if not path.exists():
            continue
        text = path.read_text("latin-1").splitlines()
        k = line - 2
        found: list[str] = []
        while k >= 0 and len(text[k]) > 6 and text[k][6] in "*/":
            found.insert(0, text[k][7:72].strip())
            k -= 1
        said = " ".join(x for x in found if x and not BANNER.match(x) and not CODE.match(x))
        if REASON.search(said) and not LEGAL.search(said):
            return f'comment at {file}:{k + 2}: "{said[:300]}"'
    return "unknown"


def hazard_sites(units: list[dict[str, Any]], gap: str) -> list[tuple[str, dict[str, Any]]]:
    return [(u["unit_id"], h) for u in units if u["kind"] == "paragraph" for h in u.get("hazards", [])
            if h["gap_id"] == gap]


def money_record(f: Facts, program: str) -> Record | None:
    fixed = [x for x in f.fields if x.get("program") == program and x["semantic_type"]["kind"] == "decimal"
             and ((x["semantic_type"]["scale"] or 0) > 0 or x["usage"] == "COMP-3")]
    if not fixed:
        return None
    units = f.units_of(program)
    rounded = hazard_sites(units, "G-ROUNDING")
    truncating = [s for s in hazard_sites(units, "G-TRUNCATE") if "decimals" in s[1]["detail"]]
    ev = [f"`{x['field_id']}` PIC {x['pic']} {x['usage']} ({x['provenance']['file']}:{x['provenance']['start_line']})"
          for x in fixed[:8] if x.get("provenance")]
    ev += [f"ROUNDED in {u} line {h['line']}" for u, h in rounded[:4]]
    ev += [f"fraction truncated in {u} line {h['line']}" for u, h in truncating[:4]]
    rounding = "ROUNDED is never used"
    if rounded:
        rounding = f"ROUNDED is used at {len(rounded)} stores"
    return Record("Fixed-point decimal arithmetic", program,
                  f"{len(fixed)} numeric items hold fixed decimal places or packed decimal; {rounding}; "
                  f"{len(truncating)} stores drop decimals by truncation.",
                  ev, "Amounts are exact decimals with fixed scale; any target type must keep scale and the "
                  "truncate/round choice per statement (G-TRUNCATE, G-ROUNDING).", "preserve",
                  lines=[(x["provenance"]["file"], x["provenance"]["start_line"]) for x in fixed[:3] if x.get("provenance")])


def truncation_record(f: Facts, program: str) -> Record | None:
    sites = hazard_sites(f.units_of(program), "G-OVERFLOW")
    if not sites:
        return None
    by_unit = {u["unit_id"]: u for u in f.units_of(program)}
    ev = [f"{u} line {h['line']}: {h['detail'][:120]}" for u, h in sites[:8]]
    where = [(by_unit[u]["span"]["file"], h["line"]) for u, h in sites[:3]]
    return Record("Silent high-order truncation", program,
                  f"{len(sites)} arithmetic statements store into a PIC without ON SIZE ERROR, so overflow "
                  "silently drops high-order digits.", ev,
                  "A faithful translation must reproduce the truncation; a redesign that raises errors changes "
                  "observable results (G-OVERFLOW).", "ask", lines=where)


def return_code_record(f: Facts, program: str) -> Record | None:
    writers = [u for u in f.units_of(program) if u["kind"] == "paragraph"
               and any(w.endswith("RETURN-CODE") for w in u["writes"])]
    if not writers:
        return None
    return Record("Errors signalled through RETURN-CODE", program,
                  f"{len(writers)} paragraphs set RETURN-CODE; callers and JCL steps see the value as the exit status.",
                  [f"{u['unit_id']} ({u['span']['file']}:{u['span']['start_line']}-{u['span']['end_line']})" for u in writers[:8]],
                  "The exit status is part of the interface (JCL COND, calling programs); keep it (G-RETCODE).",
                  "preserve", lines=[(u["span"]["file"], u["span"]["start_line"]) for u in writers[:3]])


def control_record(f: Facts, program: str) -> Record | None:
    units = [u for u in f.units_of(program) if u["kind"] == "paragraph"]
    gotos = [u for u in units if u.get("goes_to")]
    thru = [u for u in units if u.get("perform_thru")]
    if not gotos and not thru:
        return None
    ev = [f"{u['unit_id']}: GO TO {', '.join(u['goes_to'][:3])}" for u in gotos[:6]]
    ev += [f"{u['unit_id']}: PERFORM {a} THRU {b}" for u in thru[:6] for a, b in u["perform_thru"][:2]]
    return Record("Control flow through GO TO and fall-through ranges", program,
                  f"{len(gotos)} paragraphs use GO TO and {len(thru)} perform THRU ranges, so paragraphs are not "
                  "independent functions.", ev,
                  "Translate each GO TO region / THRU range as one unit (G-GOTO, G-FALLTHROUGH).", "redesign",
                  lines=[(u["span"]["file"], u["span"]["start_line"]) for u in (gotos + thru)[:3]])


def handoff_records(f: Facts) -> list[Record]:
    """Datasets written by one job step and read by a later step of the same job."""
    out: list[Record] = []
    for e in f.inventory:
        if e["kind"] != "jcl":
            continue
        written: dict[str, str] = {}
        steps: dict[str, str] = {}
        for r in e["jcl_steps"]:
            if r["kind"] == "exec":
                steps[r["step"]] = r.get("program", r.get("proc", "?"))
            if r["kind"] != "dd" or "dsn" not in r:
                continue
            if writes_dataset(r.get("disp", "")):
                written.setdefault(r["dsn"], r["step"])
            elif r["dsn"] in written and written[r["dsn"]] != r["step"]:
                w = written[r["dsn"]]
                out.append(Record("Sequential file handed between job steps", f"{e['path']}",
                                  f"Step {w} ({steps.get(w, '?')}) writes {r['dsn']}; step {r['step']} "
                                  f"({steps.get(r['step'], '?')}) reads it.",
                                  [f"{e['path']} DD {r['dd']} DSN={r['dsn']} DISP={r.get('disp', '')} (line {r['line']})"],
                                  "The dataset is an interface between programs: its record layout and order must "
                                  "stay compatible, or both steps migrate together.", "preserve",
                                  lines=[(e["path"], int(r["line"]))]))
    return out


def records(f: Facts) -> list[Record]:
    out: list[Record] = []
    for p in f.programs():
        for make in (money_record, truncation_record, return_code_record, control_record):
            r = make(f, p)
            if r is not None:
                out.append(r)
    out += handoff_records(f)
    for r in out:
        r.rationale = comment_rationale(f, r.lines)
    return out


def record_md(n: int, r: Record) -> str:
    return "\n".join([
        f"# DR-{n:03d}: {r.title} ({r.program})", "",
        "- **Status:** inferred (recovered from KB facts by a fixed trigger; not confirmed by an owner)",
        f"- **Migration implication:** {r.implication}", "",
        "## Decision as observed", "", r.decision, "",
        "## Evidence", "", *[f"- {e}" for e in r.evidence], "",
        "## Consequences", "", r.consequences, "",
        "## Rationale", "", r.rationale, ""])


# ---- writing ----------------------------------------------------------------------------------------
def documents(f: Facts) -> dict[str, str]:
    docs: dict[str, str] = {}
    for p in f.programs():
        docs[f"views/{p}.control.md"] = control_view(f, p)
        docs[f"views/{p}.data.md"] = data_view(f, p)
    flow = batch_flow(f)
    if flow is not None:
        docs["views/batch_flow.md"] = flow
    recs = records(f)
    index = ["# Recovered decision records", "", "| Id | Title | Scope | Implication |", "| --- | --- | --- | --- |"]
    for n, r in enumerate(recs, start=1):
        docs[f"decisions/DR-{n:03d}.md"] = record_md(n, r)
        index.append(f"| [DR-{n:03d}](DR-{n:03d}.md) | {r.title} | {r.program} | {r.implication} |")
    docs["decisions/README.md"] = "\n".join(index) + "\n"
    return docs


def write_docs(kb: Path, source: Path) -> dict[str, str]:
    docs = documents(Facts.load(kb, source))
    root = kb / "docs"
    for rel, text in sorted(docs.items()):
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, "utf-8")
    return docs


def stale_docs(kb: Path, source: Path) -> list[str]:
    """Docs whose bytes differ from what the current facts produce (empty = kb/docs is current)."""
    docs = documents(Facts.load(kb, source))
    root = kb / "docs"
    out = [rel for rel, text in sorted(docs.items()) if not (root / rel).exists() or (root / rel).read_text("utf-8") != text]
    present: set[str] = set()
    if root.exists():
        present = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}
    return out + sorted(present - set(docs))
