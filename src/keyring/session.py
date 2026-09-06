"""Loading an authorized Binance Agentic session.

OBSERVED: the session is obtained by authorizing through a supported client
(Part 0.2). This module reads the resulting bearer token from the local client
credential store so that KEYRING can measure the same grant the client holds.

The token is never returned in any representation intended for logging. Only
non-secret session metadata - endpoint, granted scope, expiry - is exposed for
the evidence log.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_CREDENTIAL_PATH = Path.home() / ".claude" / ".credentials.json"
DEFAULT_ENDPOINT = "https://agent.binance.com/mcp/agentic"


class SessionUnavailable(RuntimeError):
    """Raised when no authorized session can be loaded."""


@dataclass(frozen=True)
class Session:
    """An authorized Agentic session.

    `authorization` is secret. Everything else is safe to record as evidence.
    """

    endpoint: str
    authorization: str
    granted_scope: str | None = None
    expires_at: datetime | None = None
    client_id: str | None = None
    server_name: str | None = None

    def metadata(self) -> dict[str, Any]:
        """Non-secret session facts, safe for the evidence log."""
        return {
            "endpoint": self.endpoint,
            "granted_scope": self.granted_scope,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "client_id": self.client_id,
            "server_name": self.server_name,
        }

    def __repr__(self) -> str:  # pragma: no cover - defensive
        return f"Session(endpoint={self.endpoint!r}, granted_scope={self.granted_scope!r})"


def from_environment() -> Session:
    """Load a session from KEYRING_AGENTIC_* environment variables."""
    endpoint = os.environ.get("KEYRING_AGENTIC_ENDPOINT")
    authorization = os.environ.get("KEYRING_AGENTIC_AUTHORIZATION")
    if not endpoint or not authorization:
        raise SessionUnavailable(
            "KEYRING_AGENTIC_ENDPOINT and KEYRING_AGENTIC_AUTHORIZATION are required"
        )
    return Session(
        endpoint=endpoint,
        authorization=authorization,
        granted_scope=os.environ.get("KEYRING_AGENTIC_SCOPE"),
    )


def from_client_credentials(
    path: str | Path = DEFAULT_CREDENTIAL_PATH,
    server_prefix: str = "binance",
) -> Session:
    """Load the session a supported client stored after OAuth authorization."""
    path = Path(path)
    if not path.exists():
        raise SessionUnavailable(f"no client credential store at {path}")

    try:
        document = json.loads(path.read_text())
    except json.JSONDecodeError as error:
        raise SessionUnavailable(f"credential store is not readable JSON: {error}") from error

    entries = {
        key: value
        for key, value in document.get("mcpOAuth", {}).items()
        if key.startswith(server_prefix)
    }
    if not entries:
        raise SessionUnavailable(
            f"no authorized session for {server_prefix!r}; authorize through a supported client first"
        )
    if len(entries) > 1:
        raise SessionUnavailable(
            f"{len(entries)} sessions match {server_prefix!r}; refusing to guess which grant to measure"
        )

    entry = next(iter(entries.values()))
    token = entry.get("accessToken")
    if not token:
        raise SessionUnavailable("stored session carries no access token")

    expires_at = None
    if entry.get("expiresAt"):
        expires_at = datetime.fromtimestamp(entry["expiresAt"] / 1000, timezone.utc)
        if expires_at < datetime.now(timezone.utc):
            raise SessionUnavailable(f"stored session expired at {expires_at.isoformat()}")

    return Session(
        endpoint=entry.get("serverUrl", DEFAULT_ENDPOINT),
        authorization=f"Bearer {token}",
        granted_scope=entry.get("scope"),
        expires_at=expires_at,
        client_id=entry.get("clientId"),
        server_name=entry.get("serverName"),
    )


def load() -> Session:
    """Load a session from the environment, falling back to the client store."""
    try:
        return from_environment()
    except SessionUnavailable:
        return from_client_credentials()
