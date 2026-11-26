"""Runner: for each task, drive the agent loop until the verifier says green or the attempt budget is spent.
The runner owns the two built-in tools every task gets: `notes` (scratchpad) and `submit` (snapshot + verify)."""
from __future__ import annotations

from typing import Callable

from .context import ContextManager, Scratchpad
from .feedback import format_verdict
from .loop import AgentLoop
from .registry import S, ToolRegistry, obj
from .types import Candidate, Profile, Task, ToolEnv, Verdict, Verifier
from .workspace import Workspace


class Runner:
    def __init__(self, ws: Workspace, llm, verifier: Verifier, profile: Profile, log: Callable = print):
        self.ws, self.llm, self.verifier, self.profile, self.log = ws, llm, verifier, profile, log

    # ---- per-task wiring ----
    def _registry(self, task: Task, accepted: list[str], st: dict, pad: Scratchpad) -> ToolRegistry:
        cfg = self.ws.config
        reg = ToolRegistry(max_out=cfg.get("harness", {}).get("context", {}).get("max_tool_output", 5000))

        @reg.tool("notes", "Persistent scratchpad kept in your context even when old messages are dropped. "
                           "Write decisions and conventions; omit `append` to read it.", obj(append=S))
        def notes(append=None):
            if append:
                pad.append(append)
                return "noted"
            return pad.read() or "(empty)"

        @reg.tool("submit", "Snapshot the staging project and have the independent verifier check it. "
                            "Returns the verifier's report. Call only once the project builds.", obj(notes=S))
        def submit(notes=None):
            return self._submit(task, accepted, st, notes)

        env = ToolEnv(self.ws, cfg, task, accepted, st)
        for pack in self.profile.toolpacks():
            pack.register(reg, env)
        return reg

    def _submit(self, task: Task, accepted: list[str], st: dict, notes: str | None) -> str:
        if st["attempts"] >= st["max"]:
            return "ERROR: attempt budget exhausted."
        st["attempts"] += 1
        retries = self.ws.config["budgets"]["check_retries_on_error"]
        verdict = Verdict("error", "verifier did not run")
        for _ in range(1 + retries):  # verifier infrastructure errors are free retries
            sid = self.ws.submit(task.scope, list(accepted), st["attempts"], notes)
            self.ws.events.emit("check_requested", unit_id=task.id, submission_id=sid)
            try:
                verdict = self.verifier.verify(Candidate(self.ws.root, sid, task.id, task.scope, list(accepted),
                                                         st["attempts"], self.ws.config["gate"]["required_tier"]))
            except Exception as e:
                verdict = Verdict("error", f"verifier adapter failed: {type(e).__name__}: {e}")
            if verdict.status != "error":
                break
        st["verdict"], st["sid"], st["green"] = verdict, sid, verdict.green
        return format_verdict(sid, verdict) + f"\nAttempts left for this task: {st['max'] - st['attempts']}"

    # ---- main loop ----
    def run(self, only: list[str] | None = None, max_steps: int = 40) -> dict:
        cfg, hc = self.ws.config, self.ws.config.get("harness", {})
        ctx = ContextManager(**{k: v for k, v in hc.get("context", {}).items() if k in ("budget", "keep_last")})
        allow = set(hc["toolset"]) | {"notes", "submit"} if hc.get("toolset") else None
        tasks = self.profile.tasks(self.ws, only)
        self.log(f"[harness] tasks: {[t.id for t in tasks]}")
        accepted: list[str] = []
        failed: list[str] = []
        for task in tasks:
            self.ws.events.emit("unit_started", unit_id=task.id)
            st = {"attempts": 0, "max": cfg["budgets"]["attempts_per_unit"], "green": False}
            pad = Scratchpad(self.ws.run_dir / "notes" / f"{task.id}.md")
            reg = self._registry(task, accepted, st, pad)
            loop = AgentLoop(self.llm, reg, ctx, self.ws.events, allow=allow, label=task.id, log=self.log)
            why = loop.run(lambda: self.profile.system_prompt(task, pad.read()),
                           self.profile.first_message(task, accepted, cfg),
                           lambda: st["green"] or st["attempts"] >= st["max"], max_steps)
            if st["green"]:
                accepted.append(task.id)
                self.log(f"[harness] {task.id} GREEN after {st['attempts']} attempt(s)")
            else:
                failed.append(task.id)
                self.ws.events.emit("unit_abandoned", unit_id=task.id, reason=why, attempts=st["attempts"])
                self.log(f"[harness] {task.id} abandoned after {st['attempts']} attempt(s): {why}")
        return {"accepted": accepted, "failed": failed}
