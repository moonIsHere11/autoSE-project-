"""Synthetic estates for scale tests: `groups` domains of programs sharing vocabulary, copybooks and stores."""
import json
import random
import tempfile
from pathlib import Path

from planner.kb import FixtureKb


def estate_doc(n: int, idents: int = 200, groups: int = 50, seed: int = 1) -> dict:
    rng = random.Random(seed)
    vocab = [[f"G{g}W{i}" for i in range(100)] for g in range(groups)]
    programs, uses = [], []
    for i in range(n):
        g = i % groups
        words = [rng.choice(vocab[g]) + "-" + rng.choice(vocab[rng.randrange(groups)]) for _ in range(idents)]
        programs.append({"id": f"P{i:05}", "file": f"none/P{i:05}.cbl", "loc": 100, "kind": "batch", "confidence": 1.0,
                         "copybooks": ["COMMHDR", f"REC{g}"], "calls": [f"P{(i + groups) % n:05}"], "identifiers": words})
        uses.append({"program": f"P{i:05}", "store": f"TABLE{g}", "store_kind": "table",
                     "mode": "write" if i % 3 == 0 else "read"})
    return {"kb_version": "synthetic", "source_root": ".", "programs": programs, "copybooks": [],
            "store_uses": uses, "job_steps": [], "units": {}}


def estate_kb(n: int, **kw) -> FixtureKb:
    d = Path(tempfile.mkdtemp())
    (d / "estate.json").write_text(json.dumps(estate_doc(n, **kw)))
    return FixtureKb(d / "estate.json")


def phase0_workspace(n: int, units: int = 20, fields: int = 50) -> Path:
    """A Phase 0 kb/ for n programs, each with `units` paragraphs and `fields` data items and one file."""
    w = Path(tempfile.mkdtemp())
    src = w / "kb" / "source"
    src.mkdir(parents=True)
    (w / "source").mkdir()
    (w / "kb" / "manifest.json").write_text(json.dumps({"kb_version": "synthetic"}))
    inv = [{"path": f"P{i:05}.cbl", "kind": "program", "lines": 10, "programs": [f"P{i:05}"], "copybooks": [],
            "calls": []} for i in range(n)]
    inv.append({"path": "JOB.jcl", "kind": "jcl", "lines": 1, "jcl_steps": [
        row for i in range(n) for row in (
            {"job": "JOB", "step": f"S{i}", "kind": "exec", "program": f"P{i:05}"},
            {"job": "JOB", "step": f"S{i}", "kind": "dd", "dd": "IN", "dsn": f"DS{i % 100}", "disp": "SHR"})]})
    (src / "inventory.json").write_text(json.dumps({"files": inv}))
    (src / "units.json").write_text(json.dumps([
        {"unit_id": f"P{i:05}.U{j}", "kind": "paragraph", "program": f"P{i:05}", "unsupported": [],
         "provenance": {"confidence": 1.0}} for i in range(n) for j in range(units)]))
    (src / "call_graph.json").write_text(json.dumps({"edges": [
        {"src": f"P{i:05}.U0", "dst": f"P{(i + 1) % n:05}", "kind": "call"} for i in range(n)]}))
    (src / "data_flow.json").write_text(json.dumps({"files": [
        {"program": f"P{i:05}", "file": "F", "organization": "SEQUENTIAL", "assign": "IN", "units": {"U0": ["R"]}}
        for i in range(n)]}))
    (src / "data_dictionary.json").write_text(json.dumps([
        {"field_id": f"P{i:05}.F{j}", "name": f"F{j}", "program": f"P{i:05}"} for i in range(n) for j in range(fields)]))
    return w
