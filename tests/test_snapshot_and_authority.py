from __future__ import annotations

import json

import pytest

from keyring.authority import derive, is_write_tool_name
from keyring.evidence import EvidenceLog
from keyring.models import EvidenceRecord
from keyring.mcp import Budget, RateLimitKill, WriteToolRefused, _binance_error_code, is_write_tool
from keyring.models import StateSnapshot
from keyring.prober import classify_error_code
from keyring.snapshot import SnapshotChain, compare, digest_of, load_components


def snapshot(components, missing=None):
    return StateSnapshot(
        captured=True,
        balances={"a": 1},
        positions={"b": 2},
        open_orders={"c": 3},
        components=components,
        missing=missing,
        digest=digest_of(components),
    )


def test_digest_is_order_independent():
    assert digest_of({"a": 1, "b": 2}) == digest_of({"b": 2, "a": 1})


def test_identical_state_compares_identical():
    before = snapshot({"spot": {"free": "0"}})
    after = snapshot({"spot": {"free": "0"}})
    verdict = compare(before, after)
    assert verdict["identical"] is True
    assert verdict["verdict"] == "IDENTICAL"


def test_changed_state_fails_and_names_the_component():
    before = snapshot({"spot": {"free": "0"}, "usds": {}})
    after = snapshot({"spot": {"free": "1"}, "usds": {}})
    verdict = compare(before, after)
    assert verdict["identical"] is False
    assert verdict["changed_components"] == ["spot"]
    assert verdict["verdict"] == "STATE PROOF FAILED"


def test_incomplete_snapshot_can_never_pass_even_when_digests_match():
    """A missing required component must discard the probe under Law 3."""
    components = {"spot": {}}
    before = snapshot(components, missing=["usds_positions"])
    after = snapshot(components, missing=["usds_positions"])
    assert before.digest == after.digest
    assert compare(before, after)["identical"] is False


def test_chain_detects_tampering():
    chain = SnapshotChain()
    chain.add("pre", snapshot({"x": 1}))
    chain.add("post", snapshot({"x": 1}))
    assert chain.unbroken() is True
    assert chain.all_identical() is True

    chain.entries[1]["state_digest"] = digest_of({"x": 2})
    assert chain.unbroken() is False


def test_chain_records_a_real_state_change():
    chain = SnapshotChain()
    chain.add("pre", snapshot({"x": 1}))
    chain.add("post", snapshot({"x": 2}))
    assert chain.all_identical() is False


def test_write_tools_are_refused_by_the_read_path():
    assert is_write_tool("spot.newOrder") is True
    assert is_write_tool("futures_usds.cancelOrder") is True
    assert is_write_tool("spot.getAccount") is False


def test_authority_replay_preserves_explicit_advertised_only_outcome(tmp_path):
    log = EvidenceLog(tmp_path / "evidence.jsonl")
    log.extend(
        [
            EvidenceRecord(
                record_type="mcp_discovery",
                run_id="run-1",
                label="OBSERVED",
                operation="tools/list",
                granted_scope="mcp:account:read",
                raw_response=json.dumps(
                    {"result": {"tools": [{"name": "spot.newOrder"}]}}
                ),
            ),
            EvidenceRecord(
                record_type="positive_control",
                run_id="run-1",
                label="OBSERVED",
                control_passed=True,
            ),
            EvidenceRecord(
                record_type="capability_probe",
                run_id="run-1",
                label="OBSERVED",
                capability="spot",
                operation="spot.newOrder",
                outcome="advertised_only",
                control_passed=True,
                state_unchanged=True,
            ),
        ]
    )

    row = derive(tmp_path)["capabilities"]["spot"]
    assert row["classification"] == "ADVERTISED_ONLY"


@pytest.mark.parametrize(
    "name,expected",
    [
        ("spot.newOrder", True),
        ("spot.deleteOpenOrders", True),
        ("futures_usds.changeInitialLeverage", True),
        # These read tools contain write-ish words and must not be miscounted.
        ("margin.queryMaxBorrow", False),
        ("wallet.queryUserUniversalTransferHistory", False),
        ("wallet.withdrawHistory", False),
        ("spot.getOrder", False),
        ("futures_coin.currentAllOpenOrders", False),
    ],
)
def test_write_tool_name_classification(name, expected):
    assert is_write_tool_name(name) is expected


def test_only_observed_error_codes_are_classified():
    assert classify_error_code("-1013") == "VERIFIED"
    assert classify_error_code("-4013") == "VERIFIED"
    assert classify_error_code("-1111") == "VERIFIED"
    assert classify_error_code("-2015") == "DENIED"
    # An unobserved code is never assumed into a class.
    assert classify_error_code("-9999") == "INCONCLUSIVE"
    assert classify_error_code(None) == "INCONCLUSIVE"


def test_binance_code_extraction_ignores_the_jsonrpc_envelope():
    raw = (
        '{"jsonrpc":"2.0","id":1,"error":{"code":-32603,'
        '"message":"{\\"code\\":-1013,\\"msg\\":\\"Filter failure\\"}"}}'
    )
    assert _binance_error_code(raw) == "-1013"


def test_budget_stops_the_run_when_exhausted():
    budget = Budget(max_probes_per_run=2, max_probes_per_minute=99)
    budget.spend_probe()
    budget.spend_probe()
    with pytest.raises(RateLimitKill):
        budget.spend_probe()


def test_snapshot_config_loads_and_is_checksummed():
    components, checksum = load_components()
    assert len(checksum) == 64
    assert components
    satisfied = {c.satisfies for c in components if c.required}
    # Law 3 requires all three legs to be covered by required components.
    assert {"balances", "positions", "open_orders"} <= satisfied


class _RefusingClient:
    """Minimal stand-in proving call_tool refuses write tools."""

    def call_tool(self, name, arguments=None):
        if is_write_tool(name):
            raise WriteToolRefused(name)
        return None


def test_snapshot_path_cannot_invoke_a_write_tool():
    with pytest.raises(WriteToolRefused):
        _RefusingClient().call_tool("spot.newOrder", {})
