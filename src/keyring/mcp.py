"""Streamable-HTTP MCP client for the Binance Agentic gateway.

OBSERVED: the gateway requires an `initialize` call before it will answer
`tools/list`, and returns no `Mcp-Session-Id` header. Both behaviours are
handled here.

Two safety properties are enforced in code rather than by convention:

* A tool whose name matches a state-changing verb cannot be invoked through
  `call_tool`. Invoking one requires `probe()`, which is explicit at the call
  site and is what the evidence log records as a probe.
* Rate-limit responses are handled per Law 8: `429` backs off honouring
  `Retry-After`, `418` kills the run outright, `403` halts, and `5xx` raises so
  the caller records INCONCLUSIVE rather than retrying aggressively.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from .session import Session

PROTOCOL_VERSION = "2025-06-18"

# ASSUMED: name-based classification of state-changing tools. Derived from the
# OBSERVED tool surface, where every write tool matched one of these verbs.
WRITE_VERB = re.compile(
    r"(newOrder|cancelOrder|deleteOrder|deleteOpenOrders|changeInitialLeverage"
    r"|changeMarginType|[Tt]ransfer|[Bb]orrow|[Rr]epay|[Ww]ithdraw|acceptQuote|placeOrder)"
)


class RateLimitKill(RuntimeError):
    """418 or an equivalent ban signal. The run stops and does not retry."""


class AccessHalt(RuntimeError):
    """403. The run halts pending investigation."""


class Inconclusive(RuntimeError):
    """5xx or an uninterpretable response. Never retried aggressively."""


class WriteToolRefused(RuntimeError):
    """A state-changing tool was requested through the read-only path."""


def is_write_tool(name: str) -> bool:
    return bool(WRITE_VERB.search(name))


@dataclass
class Budget:
    """Law 7 and Law 8 budget, enforced in code."""

    max_probes_per_run: int = 7
    max_probes_per_minute: int = 2
    probes_used: int = 0
    _probe_times: list[float] = field(default_factory=list)
    last_429: str | None = None
    status: str = "HEALTHY"

    def spend_probe(self) -> None:
        if self.probes_used >= self.max_probes_per_run:
            raise RateLimitKill(
                f"probe budget exhausted: {self.probes_used}/{self.max_probes_per_run}"
            )
        now = time.monotonic()
        self._probe_times = [t for t in self._probe_times if now - t < 60]
        if len(self._probe_times) >= self.max_probes_per_minute:
            wait = 60 - (now - self._probe_times[0])
            time.sleep(max(wait, 0))
            now = time.monotonic()
            self._probe_times = [t for t in self._probe_times if now - t < 60]
        self._probe_times.append(now)
        self.probes_used += 1

    def report(self) -> dict[str, Any]:
        return {
            "probe_budget": f"{self.probes_used} / {self.max_probes_per_run} used this run",
            "rate_limit_status": self.status,
            "last_429": self.last_429 or "none",
        }


@dataclass
class ToolResult:
    """A raw tool response plus its decoded payload."""

    name: str
    request: dict[str, Any]
    raw: str
    http_status: int
    payload: Any = None
    error_code: str | None = None
    is_error: bool = False


class McpClient:
    def __init__(
        self,
        session: Session,
        *,
        budget: Budget | None = None,
        timeout_seconds: float = 30,
        min_interval_seconds: float = 0.2,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.session = session
        self.budget = budget or Budget()
        self._min_interval = min_interval_seconds
        self._last_call = 0.0
        self._client = httpx.Client(
            timeout=timeout_seconds,
            transport=transport,
            headers={
                "Authorization": session.authorization,
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
                "MCP-Protocol-Version": PROTOCOL_VERSION,
            },
        )
        self._request_id = 0
        self._initialized = False

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "McpClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    def _post(self, payload: dict[str, Any], *, attempt: int = 0) -> httpx.Response:
        gap = time.monotonic() - self._last_call
        if gap < self._min_interval:
            time.sleep(self._min_interval - gap)

        response = self._client.post(self.session.endpoint, json=payload)
        self._last_call = time.monotonic()

        if response.status_code == 418:
            self.budget.status = "KILLED"
            raise RateLimitKill("418 received; stopping immediately and not retrying")
        if response.status_code == 403:
            self.budget.status = "HALTED"
            raise AccessHalt("403 received; halting for investigation")
        if response.status_code == 429:
            self.budget.status = "BACKING_OFF"
            self.budget.last_429 = time.strftime("%H:%M:%S")
            if attempt >= 4:
                raise Inconclusive("429 persisted through backoff")
            retry_after = response.headers.get("Retry-After")
            delay = float(retry_after) if retry_after and retry_after.isdigit() else 2**attempt
            time.sleep(min(delay, 60))
            return self._post(payload, attempt=attempt + 1)
        if response.status_code >= 500:
            raise Inconclusive(f"{response.status_code} from gateway; not retrying aggressively")

        if self.budget.status == "BACKING_OFF":
            self.budget.status = "HEALTHY"
        return response

    def initialize(self) -> ToolResult:
        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "initialize",
            "params": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "keyring-audit", "version": "0.1.0"},
            },
        }
        response = self._post(payload)
        self._initialized = response.status_code == 200
        return ToolResult(
            name="initialize",
            request=payload,
            raw=response.text,
            http_status=response.status_code,
            payload=_decode(response),
        )

    def list_tools(self) -> tuple[list[dict[str, Any]], list[ToolResult]]:
        """Page through the advertised tool surface. Discovery only."""
        if not self._initialized:
            self.initialize()

        tools: list[dict[str, Any]] = []
        results: list[ToolResult] = []
        cursor: str | None = None

        while True:
            payload = {
                "jsonrpc": "2.0",
                "id": self._next_id(),
                "method": "tools/list",
                "params": {"cursor": cursor} if cursor else {},
            }
            response = self._post(payload)
            result = ToolResult(
                name="tools/list",
                request=payload,
                raw=response.text,
                http_status=response.status_code,
                payload=_decode(response),
            )
            results.append(result)
            if response.status_code != 200:
                break
            body = response.json().get("result", {})
            tools.extend(body.get("tools", []))
            cursor = body.get("nextCursor")
            if not cursor:
                break

        return tools, results

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> ToolResult:
        """Invoke a READ tool. Refuses anything that could change state."""
        if is_write_tool(name):
            raise WriteToolRefused(
                f"{name} is state-changing; use probe() so the call is recorded as a probe"
            )
        return self._invoke(name, arguments or {})

    def probe(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        """Invoke a capability probe. Spends probe budget (Laws 7 and 8)."""
        self.budget.spend_probe()
        return self._invoke(name, arguments)

    def _invoke(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        if not self._initialized:
            self.initialize()
        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }
        response = self._post(payload)
        decoded = _decode(response)
        error_code = _binance_error_code(response.text)
        body = response.json() if response.status_code == 200 else {}
        return ToolResult(
            name=name,
            request=payload,
            raw=response.text,
            http_status=response.status_code,
            payload=decoded,
            error_code=error_code,
            is_error="error" in body or bool(body.get("result", {}).get("isError")),
        )


def _decode(response: httpx.Response) -> Any:
    """Pull the useful payload out of an MCP tool response."""
    try:
        body = response.json()
    except ValueError:
        return None
    if "error" in body:
        return body["error"]
    result = body.get("result", {})
    if "structuredContent" in result:
        return result["structuredContent"]
    content = result.get("content")
    if isinstance(content, list) and content and "text" in content[0]:
        try:
            return json.loads(content[0]["text"])
        except (ValueError, TypeError):
            return content[0]["text"]
    return result


_BINANCE_CODE = re.compile(r'\\?"code\\?"\s*:\s*(-?\d{4,5})')


def _binance_error_code(raw: str) -> str | None:
    """Extract a Binance error code if one is present.

    OBSERVED: spot returns -1xxx / -2xxx codes; USDS-M futures returns -4xxx
    codes for the same class of parameter rejection (for example -4013, "Price
    less than min price"). The JSON-RPC envelope's own -32603 is excluded.
    """
    for candidate in _BINANCE_CODE.findall(raw):
        if candidate == "-32603":
            continue
        if candidate.startswith(("-1", "-2", "-3", "-4")):
            return candidate
    return None
