"""Minimal dependency-free LLM clients (urllib) for the ReAct loop.

  provider "anthropic": POST {base}/v1/messages        key: ANTHROPIC_API_KEY, base: ANTHROPIC_BASE_URL
  provider "openai":    POST {base}/chat/completions   key: OPENAI_API_KEY,    base: OPENAI_BASE_URL
The OpenAI-compatible client also serves self-hosted open-weight models (vLLM, Ollama, SGLang).
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    calls: int = 0
    seconds: float = 0.0

    def add(self, i: int, o: int, s: float) -> None:
        self.input_tokens += i
        self.output_tokens += o
        self.calls += 1
        self.seconds += s


@dataclass
class LLM:
    provider: str
    model: str
    temperature: float = 0.0
    max_tokens: int = 2048
    base_url: str | None = None
    api_key: str | None = None                    # overrides ANTHROPIC_API_KEY / OPENAI_API_KEY when given
    headers: dict = field(default_factory=dict)   # extra headers; may override User-Agent
    usage: Usage = field(default_factory=Usage)
    retries: int = 5                              # attempts per request (with exponential backoff)

    def _request_headers(self, url: str, headers: dict) -> dict:
        """OpenCode Go drops requests that omit x-opencode-session. One id per client, so a
        multi-turn episode stays on the same session. An id already supplied by the caller is kept."""
        merged = {**self.headers, **headers}
        if "opencode.ai/inference/go" in url and not any(k.lower() == "x-opencode-session" for k in merged):
            merged["x-opencode-session"] = self.__dict__.setdefault("_opencode_session", str(uuid.uuid4()))
        return merged

    def _post(self, url: str, payload: dict, headers: dict, retries: int | None = None) -> dict:
        retries = retries or self.retries
        data = json.dumps(payload).encode()
        for attempt in range(retries):
            req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json",
                                                                  "User-Agent": "agentheal/1.0 (research benchmark)",
                                                                  "Accept": "application/json",
                                                                  **self._request_headers(url, headers)})
            try:
                with urllib.request.urlopen(req, timeout=float(os.environ.get("AGENTHEAL_LLM_TIMEOUT", "90"))) as r:
                    return json.loads(r.read())
            except urllib.error.HTTPError as e:
                body = e.read().decode(errors="replace")[:500]
                if e.code in (429, 500, 502, 503, 529) and attempt < retries - 1:
                    time.sleep(2 ** attempt * 3)
                    continue
                raise RuntimeError(f"LLM HTTP {e.code}: {body}") from None
            except (urllib.error.URLError, TimeoutError, ConnectionError):
                if attempt < retries - 1:
                    time.sleep(2 ** attempt * 3)
                    continue
                raise
        raise RuntimeError("unreachable")

    def _post_openai(self, url: str, payload: dict, headers: dict) -> dict:
        """Chat-completions request that adapts to reasoning models (e.g. gpt-5, o-series), which reject
        max_tokens, a non-default temperature or stop sequences. Adaptations are remembered for later calls."""
        compat = self.__dict__.setdefault("_compat", set())
        for _ in range(4):
            p = dict(payload)
            if "max_completion_tokens" in compat:
                p["max_completion_tokens"] = max(4 * self.max_tokens, 8192)   # reasoning tokens count too
                p.pop("max_tokens", None)
            if "no_temperature" in compat:
                p.pop("temperature", None)
            if "no_stop" in compat:
                p.pop("stop", None)
            try:
                return self._post(url, p, headers)
            except RuntimeError as e:
                msg = str(e)
                if not msg.startswith("LLM HTTP 400"):
                    raise
                if "max_tokens" in msg and "max_completion_tokens" not in compat:
                    compat.add("max_completion_tokens")
                elif "temperature" in msg and "no_temperature" not in compat:
                    compat.add("no_temperature")
                elif "stop" in msg and "no_stop" not in compat and "stop" in p:
                    compat.add("no_stop")
                else:
                    raise
        return self._post(url, p, headers)

    def _post_anthropic(self, url: str, payload: dict, headers: dict) -> dict:
        """Messages request that drops temperature when a model rejects it as deprecated.
        The adaptation is remembered for later calls on this client."""
        compat = self.__dict__.setdefault("_compat", set())
        for _ in range(3):
            p = dict(payload)
            if "no_temperature" in compat:
                p.pop("temperature", None)
            try:
                return self._post(url, p, headers)
            except RuntimeError as e:
                msg = str(e)
                if msg.startswith("LLM HTTP 400") and "temperature" in msg and "no_temperature" not in compat:
                    compat.add("no_temperature")
                    continue
                raise
        return self._post(url, p, headers)

    def complete(self, system: str, messages: list[dict], stop: list[str] | None = None) -> str:
        """messages: [{"role": "user"|"assistant", "content": str | [parts]}]; parts may include
        {"type": "image", "data": <base64 png>}."""
        t0 = time.time()
        if self.provider == "anthropic":
            base = self.base_url or os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com")
            msgs = [{"role": m["role"], "content": _anthropic_parts(m["content"])} for m in messages]
            payload = {"model": self.model, "system": system, "messages": msgs, "max_tokens": self.max_tokens,
                       "temperature": self.temperature}
            if stop:
                payload["stop_sequences"] = stop
            out = self._post_anthropic(f"{base.rstrip('/')}/v1/messages", payload,
                                       {"x-api-key": self.api_key or os.environ.get("ANTHROPIC_API_KEY", ""),
                                        "anthropic-version": "2023-06-01"})
            text = "".join(b.get("text", "") for b in out.get("content", []) if b.get("type") == "text")
            u = out.get("usage", {})
            self.usage.add(u.get("input_tokens", 0), u.get("output_tokens", 0), time.time() - t0)
            return text
        base = self.base_url or os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
        msgs = [{"role": "system", "content": system}] + [{"role": m["role"], "content": _openai_parts(m["content"])}
                                                           for m in messages]
        payload = {"model": self.model, "messages": msgs, "max_tokens": self.max_tokens,
                   "temperature": self.temperature}
        if stop:
            payload["stop"] = stop
        out = self._post_openai(f"{base.rstrip('/')}/chat/completions", payload,
                                {"Authorization": f"Bearer {self.api_key or os.environ.get('OPENAI_API_KEY', '')}"})
        ch = out["choices"][0]
        text = ch["message"].get("content") or ""
        self.last_finish = ch.get("finish_reason")
        self.last_reasoning_chars = len(ch["message"].get("reasoning_content") or ch["message"].get("reasoning") or "")
        u = out.get("usage", {})
        self.usage.add(u.get("prompt_tokens", 0), u.get("completion_tokens", 0), time.time() - t0)
        return text


def _anthropic_parts(content):
    if isinstance(content, str):
        return content
    parts = []
    for p in content:
        if p.get("type") == "image":
            parts.append({"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": p["data"]}})
        else:
            parts.append({"type": "text", "text": p["text"]})
    return parts


def _openai_parts(content):
    if isinstance(content, str):
        return content
    parts = []
    for p in content:
        if p.get("type") == "image":
            parts.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{p['data']}"}})
        else:
            parts.append({"type": "text", "text": p["text"]})
    return parts
