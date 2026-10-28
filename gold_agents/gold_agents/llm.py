"""The language-model seam. Agents ask for JSON; a fake stands in for tests; no key means rules-only mode.

The model sees NUMBERS the code computed, never a chart image and never anything after the as-of time.
"""
from __future__ import annotations

import json
import os
import re
from typing import Protocol


class LLM(Protocol):
    def complete_json(self, *, model: str, system: str, user: str, max_tokens: int) -> dict: ...


def parse_json(text: str) -> dict:
    """Pull the first JSON object out of a reply, tolerating code fences and chatter around it."""
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    else:
        start = text.find("{")
        if start == -1:
            raise ValueError(f"no JSON object in model reply: {text[:120]!r}")
        # The FIRST complete object: a reply that adds a note (or a second object) after it used to fail with "Extra data".
        return json.JSONDecoder().raw_decode(text[start:])[0]
    return json.loads(text)


class AnthropicLLM:
    def __init__(self, api_key: str | None = None):
        import anthropic
        self._client = anthropic.Anthropic(api_key=api_key or os.environ["ANTHROPIC_API_KEY"])
        self.calls = 0
        self.input_tokens = 0
        self.output_tokens = 0

    def complete_json(self, *, model: str, system: str, user: str, max_tokens: int) -> dict:
        msg = self._client.messages.create(model=model, max_tokens=max_tokens, system=system,
                                           messages=[{"role": "user", "content": user}])
        self.calls += 1
        self.input_tokens += msg.usage.input_tokens
        self.output_tokens += msg.usage.output_tokens
        return parse_json("".join(b.text for b in msg.content if getattr(b, "type", "") == "text"))


class FakeLLM:
    """Returns canned dicts by a marker found in the system prompt; records every call for assertions."""
    def __init__(self, replies: dict[str, dict] | None = None, default: dict | None = None):
        self.replies = replies or {}
        self.default = default
        self.calls: list[dict] = []

    def complete_json(self, *, model: str, system: str, user: str, max_tokens: int) -> dict:
        self.calls.append({"model": model, "system": system, "user": user})
        for marker, reply in self.replies.items():
            if marker in system:
                return reply
        if self.default is not None:
            return self.default
        raise RuntimeError("FakeLLM has no reply for this prompt")


def from_env() -> AnthropicLLM | None:
    """An Anthropic client when ANTHROPIC_API_KEY is set (env or gold_agents/.env), else None."""
    from pathlib import Path
    env = Path(__file__).resolve().parent.parent / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if line.startswith("ANTHROPIC_API_KEY=") and line.split("=", 1)[1].strip():
                os.environ.setdefault("ANTHROPIC_API_KEY", line.split("=", 1)[1].strip())
    return AnthropicLLM() if os.environ.get("ANTHROPIC_API_KEY") else None
