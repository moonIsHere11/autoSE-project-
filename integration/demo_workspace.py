#!/usr/bin/env python3
"""Build a throwaway workspace around one corpus program.
  demo_workspace.py WS PROGRAM            -> workspace + a submission of the corpus Java (correct)
  demo_workspace.py WS PROGRAM --bug      -> same, with a seeded PIC-truncation bug in the Java
  demo_workspace.py WS PROGRAM --empty    -> workspace with empty staging (for an agent to fill)"""
import json
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from harness.workspace import Workspace  # noqa: E402


def make(ws_dir: Path, prog: str, empty: bool = False, bug: bool = False, model: str | None = None) -> Workspace:
    src = REPO / "corpus" / prog
    if ws_dir.exists():
        shutil.rmtree(ws_dir)
    (ws_dir / "source").mkdir(parents=True)
    cbl = next((src / "cobol").glob("*.cbl"))
    shutil.copy(cbl, ws_dir / "source" / cbl.name)
    jar = REPO / "runtimes" / "build" / "java" / "cobolrt.jar"
    llm = {"adapter": "harness.llm.groq:GroqLLM", **({"model": model} if model else {})}
    (ws_dir / "config.yaml").write_text(json.dumps({  # JSON is valid YAML
        "run": {"id": "R-001"}, "source": {"dir": "source"},
        "target": {"language": "java", "version": "21", "classpath": str(jar) if jar.exists() else None},
        "gate": {"required_tier": "tested"}, "budgets": {"attempts_per_unit": 5, "check_retries_on_error": 1},
        "harness": {"llm": llm, "verifier": {"adapter": "adapters.verifiers.nan:NanVerifier"},
                    "profile": {"adapter": "extras.cobol_java:Profile"}, "context": {"budget": 9000}}}, indent=1))
    ws = Workspace(ws_dir)
    if not empty:
        shutil.copytree(src / "java", ws.staging, dirs_exist_ok=True)
        if bug:  # PIC S9(2)V9 narrowed to one integer digit (G-TRUNCATE)
            f = next(ws.staging.rglob("*.java"))
            f.write_text(f.read_text().replace("wsQuotR = qr % 1000;", "wsQuotR = qr % 100;", 1))
    return ws


if __name__ == "__main__":
    ws = make(Path(sys.argv[1]), sys.argv[2], empty="--empty" in sys.argv, bug="--bug" in sys.argv)
    if "--empty" in sys.argv:
        print(ws.root, "(empty staging)")
    else:
        print(ws.root, ws.submit([sys.argv[2].upper()], [], 1, "demo"))
