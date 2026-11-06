#!/usr/bin/env python3
"""End-to-end loop test with a SCRIPTED model (no LLM quota): real Phase 1 loop + tools + submit,
real `phase2 check` (Nan's verifier in Docker, GnuCOBOL oracle). Attempt 1 writes a buggy translation,
the model reads the RED report, attempt 2 writes the fixed one.   usage: e2e_scripted.py WORKSPACE_DIR"""
import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
W = Path(sys.argv[1]).resolve()
subprocess.run([sys.executable, str(REPO / "integration" / "demo_workspace.py"), str(W), "divrem", "--llm"], check=True)
os.environ.update(PHASE0_CMD=f"python3 {REPO}/integration/phase0_stub.py", PHASE2_CMD=str(REPO / "phase2/bin/phase2"),
                  GROQ_API_KEY="unused")
sys.path.insert(0, str(REPO / "phase1"))
from phase1 import agent  # noqa: E402
from phase1.workspace import Workspace  # noqa: E402

GOOD = (REPO / "corpus/divrem/java/src/main/java/corpus/Divrem.java").read_text()
BAD = GOOD.replace("wsQuotR = qr % 1000;", "wsQuotR = qr % 100;")  # PIC S9(2)V9 narrowed: G-TRUNCATE
PATH = "src/main/java/corpus/Divrem.java"


class Scripted:
    model = "scripted"

    def __init__(self):
        self.n = 0
        self.fixed = False

    def chat(self, msgs, tools):
        last = msgs[-1]["content"] if msgs[-1]["role"] == "tool" else ""
        if "verdict=RED" in last:
            print("\n--- model received RED feedback ---\n" + last[:900] + "\n-----------------------------------\n")
            self.fixed = True
            self.plan = [("write_file", {"path": PATH, "content": GOOD}), ("build", {}), ("submit", {})]
        elif self.n == 0:
            self.plan = [("write_file", {"path": PATH, "content": BAD}), ("build", {}), ("submit", {})]
        if not self.plan:
            return {"role": "assistant", "content": "done"}, {}
        name, args = self.plan.pop(0)
        self.n += 1
        return {"role": "assistant", "content": "", "tool_calls": [{"id": f"c{self.n}", "type": "function",
                "function": {"name": name, "arguments": json.dumps(args)}}]}, {}


agent.GroqClient = lambda model=None: Scripted()
res = agent.run(Workspace(W), wanted=["DIVREM"], max_steps=20)
print(json.dumps(res))
ws = W / "reports"
for r in sorted(ws.glob("S-*/report.json")):
    d = json.loads(r.read_text())
    print(r.parent.name, d["verdict"], "|", d["summary"].splitlines()[0])
