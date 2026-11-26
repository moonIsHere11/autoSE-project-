"""Compose a Runner from config.yaml. Every pluggable part is named by a 'package.module:Class' string:

harness:
  llm:      {adapter: harness.llm.groq:GroqLLM, model: openai/gpt-oss-20b}
  verifier: {adapter: adapters.verifiers.nan:NanVerifier}
  profile:  {adapter: extras.cobol_java:Profile}
  context:  {budget: 36000, keep_last: 8, max_tool_output: 5000}
  toolset:  [read_file, write_file, ...]      # optional allow-list (fewer tool schemas = fewer prompt tokens)
"""
from __future__ import annotations

from .registry import load_adapter
from .runner import Runner
from .workspace import Workspace

DEFAULTS = {"llm": "harness.llm.groq:GroqLLM", "verifier": "adapters.verifiers.nan:NanVerifier",
            "profile": "extras.cobol_java:Profile"}


def _spec(hc: dict, key: str):
    v = hc.get(key, {})
    v = {"adapter": v} if isinstance(v, str) else dict(v)
    return v.pop("adapter", DEFAULTS[key]), v


def build_runner(workspace_root, llm=None, verifier=None, profile=None, log=print) -> Runner:
    ws = Workspace(workspace_root)
    hc = ws.config.get("harness", {})
    if llm is None:
        spec, kw = _spec(hc, "llm")
        llm = load_adapter(spec, **kw)
    if verifier is None:
        spec, kw = _spec(hc, "verifier")
        verifier = load_adapter(spec, **kw)
    if profile is None:
        spec, kw = _spec(hc, "profile")
        profile = load_adapter(spec, **kw)
    return Runner(ws, llm, verifier, profile, log=log)
