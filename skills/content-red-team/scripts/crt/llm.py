"""LLM backends: real Anthropic client (vision + forced structured output) and a logging wrapper.

The API key is read from the environment only and is never logged or written.
"""
from __future__ import annotations

import base64
import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel


@dataclass
class Call:
    phase: str  # phase1 | critique | rebuttal | judge
    member_id: str
    system: str
    user: str
    schema: type[BaseModel]
    images: list[str] = field(default_factory=list)  # file paths; sent as vision blocks
    context: dict[str, Any] = field(default_factory=dict)  # used ONLY by the mock
    model: str | None = None
    max_tokens: int | None = None


class LLM(Protocol):
    def call(self, call: Call) -> BaseModel: ...


def _image_block(path: str) -> dict:
    ext = Path(path).suffix.lower().lstrip(".")
    media = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp"}.get(ext, "image/png")
    data = base64.standard_b64encode(Path(path).read_bytes()).decode()
    return {"type": "image", "source": {"type": "base64", "media_type": media, "data": data}}


class AnthropicLLM:
    def __init__(self, model: str, max_tokens: int = 6000):
        import anthropic  # imported lazily: Mode A only

        self.client = anthropic.Anthropic(max_retries=4)  # key from ANTHROPIC_API_KEY
        self.model = model
        self.max_tokens = max_tokens

    def complete(self, system: str, user: str) -> str:
        r = self.client.messages.create(
            model=self.model, max_tokens=self.max_tokens, system=system,
            messages=[{"role": "user", "content": user}],
        )
        return "".join(b.text for b in r.content if b.type == "text")

    def call(self, call: Call) -> BaseModel:
        content: list[dict] = []
        for img in call.images:
            content.append({"type": "text", "text": f"[image: {Path(img).name}]"})
            content.append(_image_block(img))
        content.append({"type": "text", "text": call.user})
        tool = {"name": "submit", "description": "Submit your structured answer.",
                "input_schema": call.schema.model_json_schema()}
        r = self.client.messages.create(
            model=call.model or self.model,
            max_tokens=call.max_tokens or self.max_tokens,
            system=call.system,
            messages=[{"role": "user", "content": content}],
            tools=[tool],
            tool_choice={"type": "tool", "name": "submit"},
        )
        for b in r.content:
            if b.type == "tool_use":
                return call.schema.model_validate(b.input)
        raise RuntimeError("model returned no structured answer")


class LoggedLLM:
    """Wraps any LLM: records every prompt (for isolation tests) and timings (for parallelism tests)."""

    def __init__(self, inner: LLM, log_path: Path | None = None):
        self.inner = inner
        self.log_path = log_path
        self._lock = threading.Lock()
        self.records: list[dict[str, Any]] = []
        self._active = 0
        self.max_active = 0

    def call(self, call: Call) -> BaseModel:
        with self._lock:
            self._active += 1
            self.max_active = max(self.max_active, self._active)
        t0 = time.time()
        try:
            return self.inner.call(call)
        finally:
            t1 = time.time()
            rec = {
                "phase": call.phase, "member": call.member_id, "system": call.system, "user": call.user,
                "images": [Path(i).name for i in call.images], "start": t0, "end": t1,
            }
            with self._lock:
                self._active -= 1
                self.records.append(rec)
                if self.log_path:
                    self.log_path.parent.mkdir(parents=True, exist_ok=True)
                    with self.log_path.open("a") as f:
                        f.write(json.dumps(rec) + "\n")
