#!/usr/bin/env python3
"""Build a throwaway workspace around one corpus program and submit its Java translation through
Phase 1's real submit(), so `phase2 check` (Nan's verifier behind the adapter) runs end to end.
usage: demo_workspace.py WORKSPACE_DIR PROGRAM [--bug]      e.g. ... /tmp/ws divrem --bug"""
import json
import re
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "phase1"))
from phase1.workspace import Workspace  # noqa: E402


def main():
    ws_dir, prog = Path(sys.argv[1]), sys.argv[2]
    bug = "--bug" in sys.argv
    src = REPO / "corpus" / prog
    if ws_dir.exists():
        shutil.rmtree(ws_dir)
    (ws_dir / "source").mkdir(parents=True)
    cbl = next((src / "cobol").glob("*.cbl"))
    shutil.copy(cbl, ws_dir / "source" / cbl.name)
    (ws_dir / "config.yaml").write_text(
        f"run: {{id: R-001}}\nsource: {{entry: source/{cbl.name}, dialect: default}}\n"
        "target: {language: java, version: '21'}\ngate: {required_tier: tested}\n"
        "budgets: {attempts_per_unit: 5, check_retries_on_error: 1}\n")
    (ws_dir / "kb" / "target").mkdir(parents=True)
    (ws_dir / "kb" / "manifest.json").write_text(json.dumps({"schema_version": "1.0", "kb_version": "demo-kb-1"}))
    (ws_dir / "kb" / "target" / "toolchain.json").write_text(json.dumps(
        {"language": "java", "version": "21", "file_ext": ".java", "build_cmd": ["javac"], "runtime_dir": "cobolrt"}))
    rt = REPO / "runtimes" / "build" / "java" / "cobolrt.jar"
    tcj = json.loads((ws_dir / "kb" / "target" / "toolchain.json").read_text())
    tcj["build_cmd"] = ["sh", "-c", f"mkdir -p /tmp/p1build && javac -cp {rt} -d /tmp/p1build $(find . -name '*.java')"]
    (ws_dir / "kb" / "target" / "toolchain.json").write_text(json.dumps(tcj))
    (ws_dir / "kb" / "target" / "semantic_gaps.json").write_text(json.dumps([
        {"gap_id": "G-TRUNCATE", "topic": "decimal truncation", "cobol_behavior": "values wider than the PIC lose high-order digits (MOVE/COMPUTE); extra decimals are truncated unless ROUNDED",
         "target_default": "long/BigDecimal keep every digit", "required_handling": "mask to the PIC width: value % 10^digits on the scaled integer", "rule_ids": ["R-MOVE"]},
        {"gap_id": "G-SIGN", "topic": "unsigned store", "cobol_behavior": "storing a negative into an unsigned PIC keeps the magnitude",
         "target_default": "keeps the sign", "required_handling": "Math.abs before storing into unsigned fields", "rule_ids": []},
        {"gap_id": "G-ROUNDING", "topic": "rounding", "cobol_behavior": "ROUNDED rounds half away from zero",
         "target_default": "HALF_EVEN or truncation", "required_handling": "use RoundingMode.HALF_UP on magnitude", "rule_ids": []}]))
    (ws_dir / "kb" / "target" / "mapping_rules.json").write_text(json.dumps([
        {"rule_id": "R-DISPLAY", "cobol_construct": "DISPLAY", "required_pattern": "print numerics zero-padded to PIC width with sign char for signed fields",
         "example_cobol": "DISPLAY WS-A", "example_target": "System.out.println(...)"}]))
    if "--llm" in sys.argv:  # agent translates from scratch: no staging, no submission
        (ws_dir / "staging").mkdir()
        (ws_dir / "config.yaml").write_text((ws_dir / "config.yaml").read_text() +
            "phase1: {granularity: program, context_budget: 9000, toolset: minimal}\n")
        print(ws_dir, "(empty staging)")
        return
    shutil.copytree(src / "java", ws_dir / "staging")
    if bug:  # seeded bug: drop a sign (what a naive translation of an unsigned MOVE does)
        f = next((ws_dir / "staging").rglob("*.java"))
        t = f.read_text()
        t2 = t.replace("wsQuotR = qr % 1000;", "wsQuotR = qr % 100;", 1)  # PIC S9(2)V9 narrowed to 1 integer digit (G-TRUNCATE)
        f.write_text(t2)
    w = Workspace(ws_dir)
    sid = w.submit([cbl.stem.upper()], [], ["java", "-cp", "."], 1, "demo" + (" (seeded bug)" if bug else ""))
    print(ws_dir, sid)


main()
