"""Small Claude Messages API client used only by the agent proposals.

The client returns text. It has no tool-calling capability and is never given
authority to invoke the Binance MCP endpoint. Callers must parse and validate
its proposal before a separate deterministic probe path can do anything.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Protocol

import httpx


class ModelError(RuntimeError):
    """The model could not produce a usable response."""


class TextModel(Protocol):
    """The only model capability KEYRING needs."""

    def complete(self, *, system: str, user: str) -> str: ...


@dataclass
class ClaudeMessagesModel:
    """Claude Messages API adapter with no MCP or exchange access."""

    api_key: str
    model: str
    endpoint: str = "https://api.anthropic.com/v1/messages"
    timeout_seconds: float = 30
    max_tokens: int = 1200
    transport: httpx.BaseTransport | None = None
    _client: httpx.Client = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._client = httpx.Client(
            timeout=self.timeout_seconds,
            transport=self.transport,
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
        )

    @classmethod
    def from_environment(cls) -> "ClaudeMessagesModel":
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        model = os.environ.get("KEYRING_MODEL") or os.environ.get("ANTHROPIC_MODEL")
        if not api_key:
            raise ModelError("ANTHROPIC_API_KEY is required for model-assisted planning")
        if not model:
            raise ModelError("KEYRING_MODEL is required; choose the Claude model explicitly")
        return cls(api_key=api_key, model=model)

    def close(self) -> None:
        self._client.close()

    def complete(self, *, system: str, user: str) -> str:
        response = self._client.post(
            self.endpoint,
            json={
                "model": self.model,
                "max_tokens": self.max_tokens,
                "system": system,
                "messages": [{"role": "user", "content": user}],
            },
        )
        if response.status_code >= 400:
            raise ModelError(f"Claude request failed with HTTP {response.status_code}")
        try:
            body = response.json()
        except ValueError as error:
            raise ModelError("Claude returned invalid JSON") from error
        text = "".join(
            block.get("text", "")
            for block in body.get("content", [])
            if block.get("type") == "text"
        )
        if not text:
            raise ModelError("Claude returned no text content")
        return text
