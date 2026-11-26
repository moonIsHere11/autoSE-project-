"""Groq chat adapter (OpenAI-compatible endpoint, stdlib only)."""
import json
import os
import time
import urllib.error
import urllib.request

from . import LLMError

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_MODEL = "openai/gpt-oss-20b"
_MALFORMED = ("tool_use_failed", "Parsing failed", "failed_generation")


class GroqLLM:
    def __init__(self, model: str | None = None, api_key: str | None = None, temperature: float = 0.2,
                 max_tokens: int | None = None):
        self.model = model or os.environ.get("HARNESS_MODEL", DEFAULT_MODEL)
        self.api_key = api_key or os.environ.get("GROQ_API_KEY")
        self.temperature = temperature
        self.max_tokens = max_tokens or int(os.environ.get("HARNESS_MAX_TOKENS", 4000))
        if not self.api_key:
            raise LLMError("GROQ_API_KEY is not set")

    def chat(self, messages, tools=None, retries: int = 7):
        body = {"model": self.model, "messages": messages, "temperature": self.temperature,
                "max_tokens": self.max_tokens}
        if "gpt-oss" in self.model:  # reasoning models otherwise burn the output budget on thinking
            body["reasoning_effort"] = "low"
        if tools:
            body["tools"], body["tool_choice"] = tools, "auto"
        data = json.dumps(body).encode()
        for i in range(retries + 1):
            req = urllib.request.Request(GROQ_URL, data=data, headers={
                "Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json",
                "User-Agent": "cobol-migration-harness/0.2"})
            try:
                with urllib.request.urlopen(req, timeout=120) as r:
                    out = json.load(r)
                return out["choices"][0]["message"], out.get("usage", {})
            except urllib.error.HTTPError as e:
                detail = e.read().decode(errors="replace")
                transient = e.code in (429, 500, 502, 503) or (e.code == 413 and "per minute" in detail)
                if transient and i < retries:
                    ra = e.headers.get("retry-after") if e.headers else None
                    time.sleep(min(float(ra) + 1, 65) if ra and ra.replace(".", "").isdigit()
                               else (20 if e.code == 413 else min(2 ** (i + 1), 30)))
                    continue
                raise LLMError(f"Groq HTTP {e.code}: {detail[:500]}",
                               recoverable=e.code == 400 and any(k in detail for k in _MALFORMED))
            except urllib.error.URLError as e:
                if i < retries:
                    time.sleep(2 ** (i + 1))
                    continue
                raise LLMError(f"Groq connection error: {e}")
