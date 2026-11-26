"""Tool packs for the translator: read/search the COBOL, write the Java project in staging, build it."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

from harness.registry import I, S, obj

CODE_EXTS = {".cbl", ".cob", ".cobol", ".cpy", ".copy", ".java", ".txt", ".md"}


def _inside(root: Path, rel: str) -> Path:
    p = (root / rel).resolve()
    if not str(p).startswith(str(root.resolve())):
        raise ValueError(f"path escapes {root.name}/")
    return p


def numbered(path: Path, start: int, end: int, max_lines: int = 200) -> str:
    lines = path.read_text(errors="replace").splitlines()
    end = min(end, start + max_lines - 1, len(lines))
    out = "\n".join(f"{i:>5}| {lines[i - 1].rstrip()}" for i in range(max(start, 1), end + 1))
    return out + (f"\n[file has {len(lines)} lines]" if end < len(lines) else "")


class FilesPack:
    """list_files / read_file / read_lines / search / write_file. COBOL source is read-only."""

    def register(self, reg, env):
        staging, source = env.workspace.staging, env.workspace.source_dir
        runtime_dir = (env.config.get("target", {}).get("runtime_dir") or "").strip("/")

        def locate(rel: str) -> Path:
            p = _inside(staging, rel)
            return p if p.exists() else _inside(source, rel)

        @reg.tool("list_files", "List files in the staging project and the COBOL source tree.")
        def list_files():
            a = sorted(f"staging/{p.relative_to(staging)}" for p in staging.rglob("*") if p.is_file())
            b = sorted(f"source/{p.relative_to(source)}" for p in source.rglob("*") if p.is_file())
            return "\n".join(a + b) or "(empty)"

        @reg.tool("read_file", "Read a file (staging project first, then the COBOL source).", obj(["path"], path=S))
        def read_file(path):
            return locate(path.removeprefix("source/").removeprefix("staging/")).read_text(errors="replace")

        @reg.tool("read_lines", "Read a line range (max 200 lines) of a staging or source file.",
                  obj(["path", "start", "end"], path=S, start=I, end=I))
        def read_lines(path, start, end):
            return numbered(locate(path.removeprefix("source/").removeprefix("staging/")), start, end)

        @reg.tool("search", "Regex search across the COBOL source and staging files; returns file:line: text.",
                  obj(["pattern"], pattern=S, max_results=I))
        def search(pattern, max_results=25):
            rx, out = re.compile(pattern, re.I), []
            for root in (source, staging):
                for p in sorted(root.rglob("*")):
                    if not (p.is_file() and p.suffix.lower() in CODE_EXTS):
                        continue
                    for i, line in enumerate(p.read_text(errors="replace").splitlines(), 1):
                        if rx.search(line) and not (len(line) > 6 and line[6] in "*/"):
                            out.append(f"{root.name}/{p.relative_to(root)}:{i}: {line.strip()}")
                            if len(out) >= min(max_results, 60):
                                return "\n".join(out) + "\n[stopped; refine the pattern]"
            return "\n".join(out) or "no matches"

        @reg.tool("write_file", "Create/overwrite a file in the staging project (path relative to the project root).",
                  obj(["path", "content"], path=S, content=S))
        def write_file(path, content):
            if runtime_dir and (path.strip("/") + "/").startswith(runtime_dir + "/"):
                return "ERROR: the runtime library is read-only; use it unchanged."
            p = _inside(staging, path)
            if p.is_dir():
                return f"ERROR: {path} is a directory; give a file path."
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content)
            return f"wrote {len(content)} chars to {path}"


class BuildPack:
    """build: run target.build_cmd inside staging and return the compiler output."""

    def register(self, reg, env):
        tgt = env.config.get("target", {})
        cmd = tgt.get("build_cmd") or default_build_cmd(tgt)

        @reg.tool("build", "Compile the staging project; returns the compiler output.")
        def build():
            r = subprocess.run(cmd, cwd=env.workspace.staging, capture_output=True, text=True, timeout=300)
            out = (r.stdout + r.stderr).strip()
            return f"exit={r.returncode}\n{out}" if out else f"exit={r.returncode} (ok)"


def default_build_cmd(target: dict) -> list[str]:
    cp = f" -cp {target['classpath']}" if target.get("classpath") else ""
    return ["sh", "-c", f'd=$(mktemp -d) && javac{cp} -d "$d" $(find . -name "*.java")']
