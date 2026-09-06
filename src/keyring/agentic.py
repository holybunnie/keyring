from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


class SessionUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class AgenticSession:
    """Explicit session material; values are never included in evidence."""

    endpoint: str
    authorization: str

    @classmethod
    def from_environment(cls) -> "AgenticSession":
        import os

        endpoint = os.environ.get("KEYRING_AGENTIC_ENDPOINT")
        authorization = os.environ.get("KEYRING_AGENTIC_AUTHORIZATION")
        if not endpoint or not authorization:
            raise SessionUnavailable("KEYRING_AGENTIC_ENDPOINT and KEYRING_AGENTIC_AUTHORIZATION are required")
        return cls(endpoint=endpoint, authorization=authorization)


class JsonRpcClient:
    """Transport-only client; it does not expose mutating convenience methods."""

    def __init__(self, session: AgenticSession, *, timeout_seconds: float = 20):
        self._session = session
        self._client = httpx.Client(
            timeout=timeout_seconds,
            headers={"Authorization": session.authorization, "Content-Type": "application/json"},
        )

    def close(self) -> None:
        self._client.close()

    def request(self, method: str, params: dict[str, Any] | None = None) -> httpx.Response:
        """Send a JSON-RPC request supplied by the caller; never opens a browser."""
        return self._client.post(
            self._session.endpoint,
            json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}},
        )

    def tools_list(self) -> httpx.Response:
        return self.request("tools/list")
