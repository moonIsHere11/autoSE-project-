"""Minimal Groq chat client (OpenAI-compatible endpoint, stdlib only)."""
import json
import os
import time
import urllib.error
import urllib.request

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_MODEL = "llama-3.3-70b-versatile"


class LLMError(RuntimeError):
    pass


class GroqClient:
    def __init__(self, model=None, api_key=None, temperature=0.2):
        self.model = model or os.environ.get("PHASE1_MODEL", DEFAULT_MODEL)
        self.api_key = api_key or os.environ.get("GROQ_API_KEY")
        self.temperature = temperature
        if not self.api_key:
            raise LLMError("GROQ_API_KEY is not set")

    def chat(self, messages, tools=None, retries=7):
        """Returns (assistant_message_dict, usage_dict)."""
        body = {"model": self.model, "messages": messages, "temperature": self.temperature,
                "max_tokens": int(os.environ.get("PHASE1_MAX_TOKENS", 6000))}
        if "gpt-oss" in self.model:  # reasoning models burn the output budget on thinking otherwise
            body["reasoning_effort"] = "low"
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        data = json.dumps(body).encode()
        for i in range(retries + 1):
            req = urllib.request.Request(GROQ_URL, data=data, headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "User-Agent": "cobol-migration-phase1/0.1",
            })
            try:
                with urllib.request.urlopen(req, timeout=120) as r:
                    out = json.load(r)
                return out["choices"][0]["message"], out.get("usage", {})
            except urllib.error.HTTPError as e:
                detail = e.read().decode(errors="replace")
                if (e.code in (429, 500, 502, 503) or (e.code == 413 and "per minute" in detail)) and i < retries:
                    ra = e.headers.get("retry-after") if e.headers else None  # Groq tells us when the TPM window frees up
                    time.sleep(min(float(ra) + 1, 65) if ra and ra.replace(".", "").isdigit() else (20 if e.code == 413 else min(2 ** (i + 1), 30)))
                    continue
                raise LLMError(f"Groq HTTP {e.code}: {detail[:500]}")
            except urllib.error.URLError as e:
                if i < retries:
                    time.sleep(2 ** (i + 1))
                    continue
                raise LLMError(f"Groq connection error: {e}")
