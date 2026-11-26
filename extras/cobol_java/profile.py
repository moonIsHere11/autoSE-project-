"""COBOL -> Java profile: plain task discovery (one task per program), prompts, and the file/build tools.
No static analysis or planning: the agent reads the COBOL itself."""
from __future__ import annotations

import re
from pathlib import Path

from harness.types import Task

from . import prompts
from .tools import BuildPack, FilesPack, default_build_cmd, numbered

COBOL_EXTS = {".cbl", ".cob", ".cobol"}


class Profile:
    def __init__(self, inline_source_lines: int = 220):
        self.inline_source_lines = inline_source_lines
        self._ws = None

    # ---- tasks: every source file with a PROCEDURE DIVISION is one program ----
    def tasks(self, ws, only=None):
        self._ws = ws
        out = []
        for p in sorted(ws.source_dir.rglob("*")):
            if p.suffix.lower() not in COBOL_EXTS or not p.is_file():
                continue
            text = p.read_text(errors="replace")
            if not re.search(r"PROCEDURE\s+DIVISION", text, re.I):
                continue  # copybook
            m = re.search(r"PROGRAM-ID\.?\s+([A-Za-z0-9-]+)", text, re.I)
            pid = (m.group(1) if m else p.stem).upper()
            if only and pid not in only:
                continue
            out.append(Task(pid, p.name, data={"file": str(p.relative_to(ws.source_dir)), "loc": len(text.splitlines())}))
        return out

    # ---- prompts ----
    def system_prompt(self, task, notes):
        t = self._ws.config.get("target", {})
        return prompts.SYSTEM.format(lang=t.get("language", "java").capitalize(), ver=t.get("version", ""),
                                     conventions=prompts.JAVA_CONVENTIONS, notes=notes or "(none)")

    def first_message(self, task, accepted, config):
        t = config.get("target", {})
        cmd = " ".join(t.get("build_cmd") or default_build_cmd(t))
        src = None
        if task.data["loc"] <= self.inline_source_lines:  # small programs fit in context: hand the text over
            src = numbered(self._ws.source_dir / task.data["file"], 1, task.data["loc"], task.data["loc"])
        return prompts.first_message(task, config["gate"]["required_tier"], cmd, src)

    def toolpacks(self):
        return [FilesPack(), BuildPack()]
