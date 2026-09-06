import pytest
import httpx

from keyring.agentic import AgenticSession, JsonRpcClient, SessionUnavailable, capture_tools_list
from keyring.evidence import EvidenceLog


def test_transport_rejects_non_discovery_calls() -> None:
    client = JsonRpcClient(AgenticSession("https://example.invalid/mcp", "Bearer test"))
    try:
        with pytest.raises(SessionUnavailable):
            client._request("tools/call", {"name": "place_order"})
    finally:
        client.close()


def test_capture_tools_list_writes_raw_response(tmp_path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.content.find(b"tools/list") >= 0
        return httpx.Response(200, json={"jsonrpc": "2.0", "result": {"tools": []}})

    log = EvidenceLog(tmp_path / "evidence.jsonl")
    record = capture_tools_list(
        AgenticSession("https://example.invalid/mcp", "Bearer test"),
        log,
        run_id="tools-1",
        transport=httpx.MockTransport(handler),
    )
    assert record.record_type == "tools_list"
    assert record.outcome == "success"
    assert log.records()[0].raw_response is not None
