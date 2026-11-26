"""KnowledgeSource over Phase 0's output files (W/kb/manifest.json, W/kb/source/*.json). Reads files only;
never imports Phase 0's code. Facts Phase 0 does not produce (DB tables, IKJEFT01 program binding) are simply
absent; the planner degrades (fewer edges, more open questions). See docs/phase2/KB_CONTRACT.md."""
from __future__ import annotations

import json
import re
from pathlib import Path

from .kb import Copybook, JobStep, Program, StoreUse

TSO_BATCH = {"IKJEFT01", "IKJEFT1A", "IKJEFT1B"}  # the real program is named in SYSTSIN, which Phase 0 does not read
GDG = re.compile(r"\(\s*[+-]?\d+\s*\)$")


def _load(path: Path, key: str) -> list:
    data = json.loads(path.read_text())
    return data if isinstance(data, list) else data.get(key, [])


def dataset_id(dsn: str, job: str) -> str:
    """PROD.X(+1) -> PROD.X (one store per GDG base); &&TEMP -> JOB:&&TEMP (temp names are local to a job)."""
    dsn = GDG.sub("", dsn.strip().upper())
    return f"{job}:{dsn}" if dsn.startswith("&&") else dsn


class Phase0Kb:
    def __init__(self, workspace: Path):
        self.ws = Path(workspace)
        src = self.ws / "kb" / "source"
        self._manifest = json.loads((self.ws / "kb" / "manifest.json").read_text())
        inventory = _load(src / "inventory.json", "files")
        self._units = _load(src / "units.json", "units")
        edges = _load(src / "call_graph.json", "edges")
        crud = _load(src / "data_flow.json", "files")
        fields = _load(src / "data_dictionary.json", "fields")

        self._copybooks = {Path(f["path"]).stem.upper(): Copybook(Path(f["path"]).stem.upper(),
                                                                  "code" if f.get("subkind") == "procedure" else "record")
                           for f in inventory if f["kind"] == "copybook"}
        self._steps, step_dds = self._job_steps(inventory)

        files = [f for f in inventory if f["kind"] == "program"]
        ids = [(f["programs"] or [Path(f["path"]).stem])[0].upper() for f in files]
        owner = {u["unit_id"]: u.get("program") for u in self._units}
        calls: dict[str, list[str]] = {pid: [] for pid in ids}
        for e in edges:
            if e.get("kind") != "call" or str(e.get("dst", "")).startswith("?"):
                continue
            src_prog = owner.get(e["src"]) or e["src"].split(".")[0]
            if src_prog in calls and e["dst"] not in calls[src_prog] and e["dst"] != src_prog:
                calls[src_prog].append(e["dst"])
        called = {d for targets in calls.values() for d in targets}
        run_by_jcl = {s.program for s in self._steps if s.program}
        self._programs = []
        for f, pid in zip(files, ids):
            units = [u for u in self._units if u.get("program") == pid]
            confs = [u["provenance"]["confidence"] for u in units if u.get("provenance")]
            names = [u["unit_id"].split(".")[-1] for u in units if u.get("kind") in ("paragraph", "section")]
            names += [x["name"] for x in fields if x.get("program") == pid and x.get("name")]
            online = any("cics" in str(s).lower() for u in units for s in u.get("unsupported", []))
            kind = "online" if online else ("subprogram" if pid in called and pid not in run_by_jcl else "batch")
            self._programs.append(Program(
                id=pid, file=f["path"], loc=f.get("lines", 0), kind=kind, confidence=max(confs, default=1.0),
                copybooks=tuple(c.upper() for c in f.get("copybooks", [])), calls=tuple(calls[pid]),
                identifiers=tuple(dict.fromkeys(n for n in names if n and n != "(MAIN)"))))
        self._uses = self._store_uses(crud, step_dds, set(ids))

    def _job_steps(self, inventory: list[dict]) -> tuple[list[JobStep], dict[tuple[str, str], dict[str, str]]]:
        """Steps in card order, plus per (job, step) the DD name -> dataset id map used to resolve ASSIGN names."""
        steps: list[JobStep] = []
        dds: dict[tuple[str, str], dict[str, str]] = {}
        for f in inventory:
            if f["kind"] != "jcl":
                continue
            cur: dict | None = None
            order: dict[str, int] = {}
            for row in f.get("jcl_steps", []):
                job = row.get("job", "")
                if row.get("kind") == "exec":
                    if cur:
                        steps.append(JobStep(**cur))
                    order[job] = order.get(job, 0) + 1
                    prog = row.get("program")
                    prog = None if (prog is None or prog.upper() in TSO_BATCH) else prog.upper()
                    cur = {"job": job, "step": row.get("step", ""), "order": order[job], "program": prog,
                           "reads": (), "writes": ()}
                    dds[(job, cur["step"])] = {}
                elif row.get("kind") == "dd" and cur and row.get("dsn"):
                    ds = dataset_id(row["dsn"], job)
                    dds[(job, cur["step"])][row.get("dd", "").upper()] = ds
                    first = (row.get("disp") or "SHR").split(",")[0].strip().upper()
                    key = "writes" if first in ("NEW", "MOD") else "reads"
                    if ds not in cur[key]:
                        cur[key] = cur[key] + (ds,)
            if cur:
                steps.append(JobStep(**cur))
        return steps, dds

    def _store_uses(self, crud: list[dict], step_dds: dict, ids: set[str]) -> list[StoreUse]:
        uses: list[StoreUse] = []

        def add(u: StoreUse) -> None:
            if u not in uses:
                uses.append(u)

        for row in crud:
            prog = row["program"].upper()
            letters = {x for ops in row.get("units", {}).values() for x in ops}
            assign = (row.get("assign") or row["file"]).upper()
            ds = next((step_dds[(s.job, s.step)].get(assign) for s in self._steps
                       if s.program == prog and step_dds[(s.job, s.step)].get(assign)), None)
            store, kind = (ds, "dataset") if ds else (f"{prog}:{assign}", "private")
            if letters & {"C", "U", "D"}:
                add(StoreUse(prog, store, kind, "write"))
            if "R" in letters:
                add(StoreUse(prog, store, kind, "read"))
        for s in self._steps:  # the step's DDs: covers programs whose file use Phase 0 could not parse
            if s.program in ids:
                for ds in s.reads:
                    add(StoreUse(s.program, ds, "dataset", "read"))
                for ds in s.writes:
                    add(StoreUse(s.program, ds, "dataset", "write"))
        return uses

    def programs(self) -> list[Program]:
        return list(self._programs)

    def copybooks(self) -> dict[str, Copybook]:
        return dict(self._copybooks)

    def store_uses(self) -> list[StoreUse]:
        return list(self._uses)

    def job_steps(self) -> list[JobStep]:
        return list(self._steps)

    def units(self, program_id: str) -> list[dict]:
        return [u for u in self._units if u.get("program") == program_id]

    def source_root(self) -> Path:
        return (self.ws / "source").resolve()

    def kb_version(self) -> str:
        return str(self._manifest.get("kb_version", "unknown"))
