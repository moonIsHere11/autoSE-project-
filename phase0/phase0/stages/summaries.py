"""Stage G (optional): LLM summaries for `Unit.summary`, grounded by a deterministic entity check.

* Off unless `config.yaml` has `phase0: {summaries: {enabled: true, ...}}`; with it off the build
  never touches the network and `summary` stays null.
* Any OpenAI-compatible chat endpoint: Ollama locally (default) or Groq (`GROQ_API_KEY`).
  Temperature 0 and a fixed seed; every answer is cached under `W/.phase0-cache/summaries/` by
  sha256(model, prompt), so a rebuild with a warm cache is byte-identical.
* Entity check (ETF, Maharaj et al. 2024): every COBOL-looking name in the summary must be one of
  the unit's own facts (its id, read/written fields, performed/GO TO/fall-through units, calls,
  88-levels of its fields). A summary that names anything else is rejected (summary stays null) and
  reported in `kb/source/summaries.json` (E11).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from phase0 import jsonio
from phase0.schema import Field_, FileCrud, Unit
from phase0.workspace import ContractError

PROMPT_VERSION = "g1"
PROVIDERS = {"ollama": "http://localhost:11434/v1", "groq": "https://api.groq.com/openai/v1"}
NAME = re.compile(r"\b[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+\b|\b[A-Z][A-Z0-9]{2,}\b")
SYSTEM = (
    "You summarise one COBOL paragraph for a migration engineer. Write 1 to 3 plain sentences about what the "
    "paragraph computes and in which order. Mention data items and paragraphs ONLY by the exact names listed under "
    "ALLOWED NAMES; never name anything else (no other fields, files, programs or paragraphs). Do not explain COBOL, "
    "do not guess business intent, do not use markdown."
)


@dataclass
class SummaryConfig:
    enabled: bool = False
    provider: str = "ollama"
    model: str = "qwen2.5:3b"
    base_url: str | None = None
    max_units: int = 0  # 0 = every paragraph

    @classmethod
    def from_config(cls, phase0: dict[str, object]) -> SummaryConfig:
        raw = phase0.get("summaries")
        if not isinstance(raw, dict):
            return cls()
        cfg = cls(enabled=bool(raw.get("enabled", False)), provider=str(raw.get("provider", "ollama")),
                  model=str(raw.get("model", "qwen2.5:3b")), max_units=int(str(raw.get("max_units", 0))))
        if raw.get("base_url"):
            cfg.base_url = str(raw["base_url"])
        if cfg.provider not in PROVIDERS:
            raise ContractError(f"phase0.summaries.provider must be one of {sorted(PROVIDERS)}")
        return cfg

    def url(self) -> str:
        return (self.base_url or PROVIDERS[self.provider]).rstrip("/") + "/chat/completions"


@dataclass
class SummaryReport:
    model: str
    generated: int = 0
    accepted: int = 0
    rejected: list[dict[str, Any]] = field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0
    cache_hits: int = 0


def allowed_names(u: Unit, fields: dict[str, Field_], files: list[FileCrud]) -> set[str]:
    names: set[str] = {c.file for c in files if u.unit_id in c.units}
    for ref in [u.unit_id, *u.reads, *u.writes, *u.performs, *u.goes_to, *u.calls]:
        names |= set(ref.split("."))
    if u.falls_through_to:
        names |= set(u.falls_through_to.split("."))
    for fid in [*u.reads, *u.writes]:
        f = fields.get(fid)
        if f is not None:
            names |= {c.name for c in f.condition_names}
    return {n for n in names if n}


def unsupported_entities(summary: str, allowed: set[str], universe: set[str]) -> list[str]:
    """Names in the summary that look like COBOL names of this program but are not in the unit's facts."""
    out: list[str] = []
    for tok in NAME.findall(summary):
        if tok in allowed:
            continue
        if "-" in tok or tok in universe:
            out.append(tok)
    return sorted(set(out))


def prompt(u: Unit, source: str, allowed: set[str]) -> str:
    facts = {"unit": u.unit_id, "reads": u.reads, "writes": u.writes, "performs": u.performs, "goes_to": u.goes_to,
             "falls_through_to": u.falls_through_to, "hazards": sorted({h.gap_id for h in u.hazards})}
    return (f"ALLOWED NAMES: {', '.join(sorted(allowed))}\n\nFACTS (from static analysis): "
            f"{json.dumps(facts, sort_keys=True)}\n\nSOURCE:\n{source}")


class Client:
    def __init__(self, cfg: SummaryConfig) -> None:
        self.cfg = cfg
        self.key = ""
        if cfg.provider == "groq":
            self.key = os.environ.get("GROQ_API_KEY", "")
            if not self.key:
                raise ContractError("phase0.summaries.provider groq needs GROQ_API_KEY")

    def chat(self, user: str) -> tuple[str, int, int]:
        body = {"model": self.cfg.model, "temperature": 0, "seed": 7, "max_tokens": 200,
                "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]}
        headers = {"Content-Type": "application/json", "User-Agent": "phase0-kb/0.1"}
        if self.key:
            headers["Authorization"] = f"Bearer {self.key}"
        req = urllib.request.Request(self.cfg.url(), data=json.dumps(body).encode(), headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                data = json.loads(resp.read())
        except urllib.error.URLError as exc:
            raise ContractError(f"summaries: cannot reach {self.cfg.url()} ({exc}); is `ollama serve` running?") from exc
        text = str(data["choices"][0]["message"]["content"] or "")
        usage = data.get("usage") or {}
        return clean(text), int(usage.get("prompt_tokens", 0)), int(usage.get("completion_tokens", 0))


def clean(text: str) -> str:
    """Drop reasoning blocks some local models emit, collapse whitespace."""
    text = re.sub(r"<think>.*?</think>", " ", text, flags=re.S)
    return " ".join(text.split())


def summarise(units: list[Unit], fields: list[Field_], files: list[FileCrud], source: Path, cache: Path,
              cfg: SummaryConfig) -> SummaryReport:
    report = SummaryReport(cfg.model)
    if not cfg.enabled:
        return report
    client = Client(cfg)
    by_id = {f.field_id: f for f in fields}
    universe = {f.name for f in fields if f.name} | {u.unit_id.split(".")[-1] for u in units} | {c.file for c in files}
    targets = [u for u in units if u.kind == "paragraph"]
    if cfg.max_units:
        targets = targets[: cfg.max_units]
    for u in targets:
        lines = (source / u.span.file).read_text("latin-1").splitlines()[u.span.start_line - 1 : u.span.end_line]
        allowed = allowed_names(u, by_id, files)
        text = cached_chat(client, cache, prompt(u, "\n".join(lines), allowed), report)
        report.generated += 1
        bad = unsupported_entities(text, allowed, universe)
        if bad or not text:
            report.rejected.append({"unit_id": u.unit_id, "unsupported_entities": bad, "summary": text})
            continue
        u.summary = text
        report.accepted += 1
    return report


def cached_chat(client: Client, cache: Path, user: str, report: SummaryReport) -> str:
    key = hashlib.sha256(json.dumps([PROMPT_VERSION, client.cfg.model, SYSTEM, user]).encode()).hexdigest()
    path = cache / "summaries" / f"{key}.json"
    if path.exists():
        report.cache_hits += 1
        return str(json.loads(path.read_text("utf-8"))["text"])
    text, tin, tout = client.chat(user)
    report.tokens_in += tin
    report.tokens_out += tout
    jsonio.write(path, {"model": client.cfg.model, "text": text, "tokens_in": tin, "tokens_out": tout})
    return text
