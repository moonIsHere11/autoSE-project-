#!/usr/bin/env python3
"""End-to-end loop with a SCRIPTED model (no LLM quota): real harness loop + tools + submit, real verifier
(Nan's, in Docker, GnuCOBOL oracle). Attempt 1 writes a buggy translation, the model reads the RED report,
attempt 2 writes the fix.   usage: e2e_scripted.py WORKSPACE_DIR"""
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "integration"))
from demo_workspace import make  # noqa: E402

from harness.config import build_runner  # noqa: E402

GOOD = (REPO / "corpus/divrem/java/src/main/java/corpus/Divrem.java").read_text()
BAD = GOOD.replace("wsQuotR = qr % 1000;", "wsQuotR = qr % 100;")
PATH = "src/main/java/corpus/Divrem.java"


class ScriptedLLM:
    model = "scripted"

    def __init__(self):
        self.n, self.plan = 0, []

    def chat(self, msgs, tools):
        last = msgs[-1]["content"] if msgs[-1]["role"] == "tool" else ""
        if "verdict=RED" in last:
            print("\n--- model received RED feedback ---\n" + last[:900] + "\n------------------------------------\n")
            self.plan = [("write_file", {"path": PATH, "content": GOOD}), ("build", {}), ("submit", {})]
        elif self.n == 0:
            self.plan = [("write_file", {"path": PATH, "content": BAD}), ("build", {}), ("submit", {})]
        if not self.plan:
            return {"role": "assistant", "content": "done"}, {}
        name, args = self.plan.pop(0)
        self.n += 1
        return {"role": "assistant", "content": "", "tool_calls": [{"id": f"c{self.n}", "type": "function",
                "function": {"name": name, "arguments": json.dumps(args)}}]}, {}


if __name__ == "__main__":
    W = Path(sys.argv[1]).resolve()
    make(W, "divrem", empty=True)
    print(json.dumps(build_runner(W, llm=ScriptedLLM()).run(["DIVREM"], max_steps=20)))
    for r in sorted((W / "reports").glob("S-*/report.json")):
        d = json.loads(r.read_text())
        print(r.parent.name, d["verdict"], "|", d["summary"].splitlines()[0])
