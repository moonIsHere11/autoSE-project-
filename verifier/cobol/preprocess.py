"""`cobc -E` preprocessing (COPY expansion, format normalisation) with caching. See spike S1."""

from __future__ import annotations

import hashlib
import json
import shlex
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from verifier.cobol.lexer import SourceLine, map_lines
from verifier.config import CobolConfig
from verifier.sandbox.docker_runner import DockerRunner, Mount

Format = Literal["fixed", "free"]


@dataclass
class Preprocessed:
    source_rel: str
    text: str
    lines: list[SourceLine]
    format: Format
    flags: list[str]
    sha256: str
    ok: bool
    diagnostics: str


def detect_format(text: str) -> Format:
    lines = [ln.expandtabs(8) for ln in text.splitlines() if ln.strip()]
    head = " ".join(lines[:5]).upper()
    if ">>SOURCE" in head and "FREE" in head:
        return "free"
    fixed = free = 0
    for ln in lines:
        if len(ln) >= 7 and ln[6] in "*/-dD" and (ln[:6].strip() == "" or ln[:6].strip().isdigit()):
            fixed += 1
            continue
        indent = len(ln) - len(ln.lstrip())
        if ln.lstrip().startswith("*>"):
            free += 1
        elif indent >= 7 or (ln[:6].strip().isdigit() and len(ln) > 7):
            fixed += 1
        else:
            free += 1
    return "free" if free > fixed else "fixed"


def is_program_source(path: Path) -> bool:
    try:
        text = path.read_text("latin-1")
    except OSError:
        return False
    up = text.upper()
    return "PROGRAM-ID" in up and "PROCEDURE" in up


def find_cobol_sources(repo: Path, cfg: CobolConfig) -> list[str]:
    out = []
    for p in sorted(repo.rglob("*")):
        if p.is_file() and p.suffix in cfg.source_suffixes and is_program_source(p):
            out.append(p.relative_to(repo).as_posix())
    return out


def copy_dirs(repo: Path, cfg: CobolConfig, sources: list[str]) -> list[str]:
    dirs: list[str] = []
    for s in sources:
        d = Path(s).parent.as_posix()
        if d not in dirs:
            dirs.append(d)
    for d in cfg.copy_dirs:
        for cand in sorted(repo.rglob(d)):
            if cand.is_dir():
                rel = cand.relative_to(repo).as_posix()
                if rel not in dirs:
                    dirs.append(rel)
    return dirs


def _repo_copy_hash(repo: Path, cfg: CobolConfig) -> str:
    h = hashlib.sha256()
    suffixes = set(cfg.copy_suffixes) | set(cfg.source_suffixes)
    for p in sorted(repo.rglob("*")):
        if p.is_file() and (p.suffix in suffixes or p.suffix == ""):
            if p.stat().st_size > 2_000_000:
                continue
            h.update(p.relative_to(repo).as_posix().encode())
            h.update(hashlib.sha256(p.read_bytes()).digest())
    return h.hexdigest()


def preprocess_all(
    runner: DockerRunner,
    cfg: CobolConfig,
    repo: Path,
    sources: list[str],
    cache_dir: Path,
) -> dict[str, Preprocessed]:
    """Run `cobc -E` for every source in one container; results are cached."""
    repo_hash = _repo_copy_hash(repo, cfg)
    incs = copy_dirs(repo, cfg, sources)
    results: dict[str, Preprocessed] = {}
    todo: list[tuple[str, list[str], str]] = []
    cache = cache_dir / "preprocess"
    cache.mkdir(parents=True, exist_ok=True)
    for rel in sources:
        fmt = detect_format((repo / rel).read_text("latin-1"))
        flags = cfg.flags(fmt)
        key = hashlib.sha256(json.dumps([rel, flags, incs, repo_hash]).encode()).hexdigest()
        cached = cache / f"{key}.json"
        if cached.exists():
            data = json.loads(cached.read_text("utf-8"))
            results[rel] = _make(rel, data["text"], fmt, flags, data["ok"], data["diag"])
        else:
            todo.append((rel, flags, key))
    if not todo:
        return results
    with tempfile.TemporaryDirectory(prefix="cv-pp-") as tmp:
        out = Path(tmp)
        lines = ["set +e", "cd /src"]
        inc_args = " ".join(f"-I {shlex.quote(d)}" for d in incs)
        for i, (rel, flags, _key) in enumerate(todo):
            lines.append(
                f"cobc -E {' '.join(shlex.quote(f) for f in flags)} {inc_args} {shlex.quote(rel)}"
                f" > /out/{i}.i 2> /out/{i}.err; echo $? > /out/{i}.rc"
            )
        script = out / "pp.sh"
        script.write_text("\n".join(lines) + "\n", "utf-8")
        res = runner.run(
            ["bash", "/out/pp.sh"],
            mounts=[Mount(repo, "/src", True), Mount(out, "/out", False)],
            timeout_s=600,
        )
        for i, (rel, flags, key) in enumerate(todo):
            fmt = "free" if "-fformat=free" in flags else "fixed"
            rc_p = out / f"{i}.rc"
            if not rc_p.exists():
                results[rel] = _make(rel, "", fmt, flags, False, f"preprocess did not run: {res.text()[-500:]}")
                continue
            ok = rc_p.read_text().strip() == "0"
            text = (out / f"{i}.i").read_text("latin-1")
            diag = (out / f"{i}.err").read_text("latin-1")
            results[rel] = _make(rel, text, fmt, flags, ok, diag)
            if ok:
                (cache / f"{key}.json").write_text(json.dumps({"text": text, "ok": ok, "diag": diag}), "utf-8")
        shutil.rmtree(out, ignore_errors=True)
    return results


def _make(rel: str, text: str, fmt: Format, flags: list[str], ok: bool, diag: str) -> Preprocessed:
    lines = [SourceLine(_strip_src(sl.file), sl.line, sl.text) for sl in map_lines(text, rel)]
    return Preprocessed(
        source_rel=rel,
        text=text,
        lines=lines,
        format=fmt,
        flags=flags,
        sha256=hashlib.sha256(text.encode("latin-1")).hexdigest(),
        ok=ok,
        diagnostics=diag,
    )


def _strip_src(path: str) -> str:
    for prefix in ("/src/", "./"):
        if path.startswith(prefix):
            return path[len(prefix) :]
    return path
