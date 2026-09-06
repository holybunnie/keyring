from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from typing import Any

import httpx

from .evidence import EvidenceLog
from .models import EvidenceRecord


class SessionUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class AgenticSession:
    """OBSERVED: explicit session material is never included in evidence."""

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
    """OBSERVED: transport exposes only the tools/list discovery request."""

    def __init__(
        self,
        session: AgenticSession,
        *,
        timeout_seconds: float = 20,
        transport: httpx.BaseTransport | None = None,
    ):
        self._session = session
        self._client = httpx.Client(
            timeout=timeout_seconds,
            headers={"Authorization": session.authorization, "Content-Type": "application/json"},
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def _request(self, method: str, params: dict[str, Any] | None = None) -> httpx.Response:
        """OBSERVED: send discovery only; never open a browser or invoke a tool."""
        if method != "tools/list":
            raise SessionUnavailable("the transport permits only tools/list until a safe adapter is configured")
        return self._client.post(
            self._session.endpoint,
            json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}},
        )

    def tools_list(self) -> httpx.Response:
        return self._request("tools/list")


def capture_tools_list(
    session: AgenticSession,
    log: EvidenceLog,
    *,
    run_id: str | None = None,
    transport: httpx.BaseTransport | None = None,
) -> EvidenceRecord:
    """OBSERVED: capture only the discovery response; no tool is invoked."""
    run_id = run_id or datetime.now(timezone.utc).strftime("tools-list-%Y%m%dT%H%M%SZ")
    client = JsonRpcClient(session, transport=transport)
    try:
        try:
            response = client.tools_list()
        except httpx.HTTPError:
            return log.append(
                EvidenceRecord(
                    record_type="tools_list",
                    run_id=run_id,
                    label="OBSERVED",
                    operation="tools/list",
                    outcome="transport_error",
                    metadata={"response_received": False},
                )
            )
        try:
            parsed: Any = response.json()
        except json.JSONDecodeError:
            parsed = None
        return log.append(
            EvidenceRecord(
                record_type="tools_list",
                run_id=run_id,
                label="OBSERVED",
                operation="tools/list",
                response=parsed,
                raw_response=response.text,
                http_status=response.status_code,
                outcome="success" if 200 <= response.status_code < 300 else "http_error",
            )
        )
    finally:
        client.close()
