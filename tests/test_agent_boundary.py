from __future__ import annotations

import json

import httpx
import pytest

from keyring.agent import KeyringAgent
from keyring.interpreter import ResponseInterpreter
from keyring.model_client import ClaudeMessagesModel
from keyring.mcp import Budget, ToolResult
from keyring.evidence import EvidenceLog
from keyring.session import Session
from keyring.planner import ProbePlanner, ProbeProposal, ProposalRejected, validate_proposal
from keyring.snapshot import SnapshotChain, SnapshotComponent


TOOL_SCHEMA = {
    "name": "spot.newOrder",
    "inputSchema": {
        "type": "object",
        "properties": {
            "symbol": {"type": "string"},
            "side": {"type": "string"},
            "type": {"type": "string"},
            "timeInForce": {"type": "string"},
            "quantity": {"type": "number"},
            "price": {"type": "number"},
        },
        "required": ["symbol", "side", "type"],
    },
}
FILTERS = [
    {"filterType": "LOT_SIZE", "minQty": "0.00001"},
    {"filterType": "MIN_NOTIONAL", "minNotional": "5"},
]


class FakeModel:
    def __init__(self, responses: list[str]):
        self.responses = iter(responses)
        self.calls: list[tuple[str, str]] = []

    def complete(self, *, system: str, user: str) -> str:
        self.calls.append((system, user))
        return next(self.responses)


def model_proposal() -> str:
    return json.dumps(
        {
            "tool_name": "spot.newOrder",
            "arguments": {
                "symbol": "BTCUSDT",
                "side": "BUY",
                "type": "LIMIT",
                "timeInForce": "GTC",
                "quantity": "0.00001",
                "price": "0.01",
            },
            "symbol": "BTCUSDT",
            "expected_filter": "MIN_NOTIONAL",
            "justification": "The positive notional is below the live minimum-notional filter.",
        }
    )


def test_static_planner_is_below_live_notional_and_explicitly_attributed() -> None:
    proposal = ProbePlanner().plan(
        capability="spot",
        tool_schema=TOOL_SCHEMA,
        symbol="BTCUSDT",
        filters=FILTERS,
        discovered_tool_names=["spot.newOrder"],
    )
    assert proposal.planned_by == "static"
    validation = validate_proposal(proposal, TOOL_SCHEMA, FILTERS, discovered_tool_names=["spot.newOrder"])
    assert validation.valid
    assert validation.notional == "2.50000"
    assert validation.min_notional == "5"


def test_validator_rejects_an_executable_sized_proposal() -> None:
    proposal = ProbeProposal(
        tool_name="spot.newOrder",
        arguments={"symbol": "BTCUSDT", "side": "BUY", "type": "LIMIT", "quantity": "1", "price": "5"},
        symbol="BTCUSDT",
        expected_filter="MIN_NOTIONAL",
        justification="not safe",
        planned_by="model",
    )
    result = validate_proposal(proposal, TOOL_SCHEMA, FILTERS, discovered_tool_names=["spot.newOrder"])
    assert result.valid is False
    assert any("not below" in reason for reason in result.reasons)


def test_model_proposal_is_replanned_until_the_deterministic_gate_accepts_it() -> None:
    model = FakeModel(
        [
            json.dumps(
                {
                    "tool_name": "spot.newOrder",
                    "arguments": {"symbol": "BTCUSDT", "side": "BUY", "type": "LIMIT", "quantity": "1", "price": "5"},
                    "symbol": "BTCUSDT",
                    "expected_filter": "MIN_NOTIONAL",
                    "justification": "bad first proposal",
                }
            ),
            model_proposal(),
        ]
    )
    planned = KeyringAgent(model).plan_probe(
        capability="spot",
        tool_schema=TOOL_SCHEMA,
        symbol="BTCUSDT",
        filters=FILTERS,
        discovered_tool_names=["spot.newOrder"],
    )
    assert planned.proposal.planned_by == "model"
    assert planned.validation.valid
    assert len(model.calls) == 2
    assert "notional is not below" in model.calls[1][1]


def test_planner_rejects_a_tool_outside_the_discovered_surface() -> None:
    model = FakeModel([model_proposal()])
    with pytest.raises(ProposalRejected):
        KeyringAgent(model).plan_probe(
            capability="spot",
            tool_schema=TOOL_SCHEMA,
            symbol="BTCUSDT",
            filters=FILTERS,
            discovered_tool_names=["spot.getAccount"],
        )


def test_boundary_preserves_generator_discovered_surface() -> None:
    planned = KeyringAgent(FakeModel([model_proposal()])).plan_probe(
        capability="spot",
        tool_schema=TOOL_SCHEMA,
        symbol="BTCUSDT",
        filters=FILTERS,
        discovered_tool_names=(name for name in ["spot.newOrder"]),
    )
    assert planned.validation.valid


def test_known_response_never_calls_the_model() -> None:
    model = FakeModel([])
    result = ResponseInterpreter(model).interpret(
        raw_response='{"code":-1013,"msg":"Filter failure"}',
        error_code="-1013",
        context={"capability": "spot"},
    )
    assert result.classifier_decision == "VERIFIED"
    assert model.calls == []


def test_unmatched_response_keeps_deterministic_inconclusive_decision_and_logs_disagreement() -> None:
    model = FakeModel([json.dumps({"classification": "VERIFIED", "reason": "looks like validation"})])
    result = ResponseInterpreter(model).interpret(
        raw_response='{"code":-9876,"msg":"unknown gateway response","token":"secret"}',
        error_code="-9876",
        context={"capability": "spot"},
    )
    assert result.classifier_decision == "INCONCLUSIVE"
    assert result.model_assisted is True
    assert result.model_classification == "VERIFIED"
    assert result.disagreement is True
    assert "secret" not in model.calls[0][1]


def test_claude_adapter_is_text_only_and_returns_message_content() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"content": [{"type": "text", "text": "{}"}]})

    model = ClaudeMessagesModel(
        api_key="test-key",
        model="claude-test",
        transport=httpx.MockTransport(handler),
    )
    try:
        assert model.complete(system="system", user="user") == "{}"
    finally:
        model.close()
    body = seen["body"]
    assert isinstance(body, dict)
    assert body["model"] == "claude-test"
    assert "tools" not in body
    assert body["messages"] == [{"role": "user", "content": "user"}]


def test_agent_runs_only_after_model_plan_and_records_the_plan(tmp_path) -> None:
    events: list[str] = []

    class OrderedModel(FakeModel):
        def complete(self, *, system: str, user: str) -> str:
            events.append("model")
            return super().complete(system=system, user=user)

    class FakeClient:
        session = Session("https://example.invalid", "Bearer test", "mcp:spot:trade")
        budget = Budget(max_probes_per_run=1, max_probes_per_minute=10)

        def call_tool(self, name, arguments):
            events.append(f"read:{name}")
            return ToolResult(name, {"name": name, "arguments": arguments}, json.dumps({"ok": True}), 200, payload={"ok": True})

        def probe(self, name, arguments):
            events.append("probe")
            return ToolResult(
                name,
                {"name": name, "arguments": arguments},
                '{"code":-1013,"msg":"Filter failure"}',
                200,
                error_code="-1013",
            )

    components = [
        SnapshotComponent("balances", "state.balances", {}, "balances", True),
        SnapshotComponent("positions", "state.positions", {}, "positions", True),
        SnapshotComponent("open_orders", "state.open_orders", {}, "open_orders", True),
    ]
    model = OrderedModel([model_proposal()])
    outcome = KeyringAgent(model).run_probe(
        FakeClient(),
        EvidenceLog(tmp_path / "evidence.jsonl"),
        SnapshotChain(),
        components,
        capability="spot",
        tool_schema=TOOL_SCHEMA,
        symbol="BTCUSDT",
        filters=FILTERS,
        discovered_tool_names=["spot.newOrder"],
        run_id="agent-run-1",
    )
    assert outcome.classification == "VERIFIED"
    assert events[0] == "model"
    assert events.index("model") < events.index("probe")
    record = EvidenceLog(tmp_path / "evidence.jsonl").records()[-1]
    assert record.planned_by == "model"
    assert record.probe_justification
    assert record.model_proposal is not None
    assert record.model_interpretation is None
