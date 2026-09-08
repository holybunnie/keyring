from __future__ import annotations

import json
from decimal import Decimal

import pytest

from keyring.financialreach import (
    WALLET_CAPABILITY,
    _capital_layers_for_gate,
    _confirmation_gate_observed,
    _latest_order_book_walk,
    _latest_quoted_wallet_balances,
    latest_complete_snapshot,
    reach,
    render,
)
from keyring.evidence import EvidenceLog
from keyring.models import EvidenceRecord
from keyring.provenance import Provenance, require_compatible_provenance

LABELS = {"OBSERVED", "DOCUMENTED", "ASSUMED", "INCONCLUSIVE"}
LAYERS = (
    "capital_visible",
    "capital_reachable_by_trading",
    "autonomous_capital_at_risk",
    "spot_holdings",
    "immediate_exit_cost",
    "futures_gross_notional_ceiling",
)


@pytest.fixture(scope="module")
def result():
    return reach()


def test_every_layer_is_labelled(result):
    """Law 1: no layer may be published without a label."""
    for key in LAYERS:
        assert result[key]["label"] in LABELS, key


def test_every_layer_gives_a_reason(result):
    for key in LAYERS:
        assert result[key]["reason"].strip(), key


def test_inconclusive_layers_have_no_value(result):
    """A layer that could not be measured must not carry a number."""
    for key in LAYERS:
        layer = result[key]
        if layer["label"] == "INCONCLUSIVE":
            assert layer["value"] is None, key


def test_futures_ceiling_is_never_asserted(result):
    """Part V: do not compute a gross notional ceiling unless rigorously derivable."""
    ceiling = result["futures_gross_notional_ceiling"]
    assert ceiling["label"] == "INCONCLUSIVE"
    assert ceiling["value"] is None
    assert "not derivable" in ceiling["reason"]


def test_autonomous_zero_is_never_attributed_to_a_gate_that_was_not_observed(result):
    """A scalar compatibility view may use only its matching gate row."""
    layer = result["autonomous_capital_at_risk"]
    gate = result["confirmation_gate"]
    if layer["label"] != "OBSERVED":
        pytest.skip("autonomous layer unresolved")
    selected = gate["selected_for_capital"]
    assert selected is not None
    assert selected["account"] == "Account B"
    assert selected["client"] == "Codex CLI"
    if not selected["gated"]:
        assert "confirmation prompt was observed" not in layer["reason"]
    else:
        assert "same account and client context" in layer["reason"]


def test_reachable_never_exceeds_visible(result):
    visible = result["capital_visible"]
    reachable = result["capital_reachable_by_trading"]
    if visible["label"] == "OBSERVED" and reachable["label"] == "OBSERVED":
        from decimal import Decimal

        assert Decimal(reachable["value"]) <= Decimal(visible["value"])


def test_autonomous_never_exceeds_reachable(result):
    reachable = result["capital_reachable_by_trading"]
    autonomous = result["autonomous_capital_at_risk"]
    if reachable["label"] == "OBSERVED" and autonomous["label"] == "OBSERVED":
        from decimal import Decimal

        assert Decimal(autonomous["value"]) <= Decimal(reachable["value"])


def test_probed_and_listed_instruments_stay_separate(result):
    instruments = result["instruments"]
    assert "spot_symbols_probed" in instruments
    assert "spot_symbols_listed_trading" in instruments
    # A merged "reachable instruments" figure would violate Part IX.
    assert "reachable_instruments" not in instruments
    if instruments["spot_symbols_listed_trading"]:
        assert instruments["spot_symbols_probed"] < instruments["spot_symbols_listed_trading"]


def test_exit_cost_is_not_asserted_when_holdings_exist(result):
    """A walk cost is only publishable if an order-book walk was actually done."""
    holdings = result["spot_holdings"]
    exit_cost = result["immediate_exit_cost"]
    if holdings["label"] == "OBSERVED" and holdings["value"]:
        assert exit_cost["label"] in {"OBSERVED", "INCONCLUSIVE"}
        if exit_cost["label"] == "OBSERVED":
            assert exit_cost["value"] is not None


def test_snapshot_used_is_complete(result):
    snapshot, _ = latest_complete_snapshot()
    assert snapshot is not None
    assert snapshot.complete()
    assert result["state_digest"] == snapshot.digest


def test_wallet_map_only_names_real_capabilities():
    from keyring.authority import CAPABILITY_PREFIX

    for capability in WALLET_CAPABILITY.values():
        assert capability in CAPABILITY_PREFIX


def test_render_marks_unresolved_layers_visibly(result):
    text = render(result)
    for key in LAYERS:
        if result[key]["label"] == "INCONCLUSIVE":
            assert "INCONCLUSIVE" in text


def test_quoted_wallet_reading_is_preferred_for_capital_units(tmp_path):
    path = tmp_path / "funded.jsonl"
    log = EvidenceLog(path)
    payload = [
        {"walletName": "Spot", "balance": "5.60", "activate": True},
        {"walletName": "USDⓈ-M Futures", "balance": "0", "activate": True},
    ]
    log.append(
        EvidenceRecord(
            record_type="financial_balance_quote",
            run_id="funded",
            label="OBSERVED",
            operation="wallet.queryUserWalletBalance",
            raw_response=json.dumps(
                {
                    "jsonrpc": "2.0",
                    "result": {
                        "content": [{"type": "text", "text": json.dumps(payload)}]
                    },
                }
            ),
            http_status=200,
            metadata={"quote_asset": "USDT"},
        )
    )

    total, per_wallet, _ = _latest_quoted_wallet_balances(tmp_path)
    assert total == Decimal("5.60")
    assert per_wallet["Spot"] == Decimal("5.60")


def test_order_book_walk_is_read_from_evidence(tmp_path):
    path = tmp_path / "walk.jsonl"
    log = EvidenceLog(path)
    log.append(
        EvidenceRecord(
            record_type="order_book_walk",
            run_id="walk",
            label="OBSERVED",
            operation="spot.depth",
            response={
                "symbol": "BTCUSDT",
                "exit_cost_usdt": "0.0054753406785",
                "levels_consumed": 1,
            },
            outcome="exit_cost_measured",
        )
    )

    value, _, payload = _latest_order_book_walk(tmp_path)
    assert value == Decimal("0.0054753406785")
    assert payload["levels_consumed"] == 1


def test_conflicting_default_gates_are_not_resolved_by_file_order(tmp_path):
    """Two clients' opposite defaults must remain two observations."""
    for filename, client, gate, outcome in (
        ("a-claude.jsonl", "Claude Code", "UNGATED", "NO_CONFIRMATION_PROMPT"),
        ("z-codex.jsonl", "Codex CLI", "CLIENT-GATED", "CONFIRMATION_PROMPT_SHOWN"),
    ):
        EvidenceLog(tmp_path / filename).append(
            EvidenceRecord(
                record_type="operator_observation",
                run_id=f"run-{client.lower().replace(' ', '-')}",
                label="OBSERVED",
                operation="client_gate_observation",
                outcome=outcome,
                gate=gate,
                metadata={
                    "account_label": "Account test",
                    "client": client,
                    "permission_mode": "default",
                    "captured_by_build": False,
                    "evidence_type": "operator observation of a client interface",
                },
            )
        )

    summary = _confirmation_gate_observed(tmp_path)

    assert summary["default_mode_conflict"] is True
    assert summary["default_mode_gated"] is None
    assert [item["client"] for item in summary["observations"]] == [
        "Claude Code",
        "Codex CLI",
    ]


def test_capital_and_gate_from_different_provenance_keys_cannot_join():
    capital = Provenance("Account A", "Claude Code", "default")
    gate = Provenance("Account B", "Codex CLI", "default")

    with pytest.raises(ValueError, match="provenance"):
        require_compatible_provenance(capital, gate)

    with pytest.raises(ValueError, match="different provenance accounts"):
        _capital_layers_for_gate(
            {
                "provenance_key": gate.key,
                "account": gate.account,
                "client": gate.client,
                "permission_mode": gate.permission_mode,
                "gated": True,
                "source": "gate.jsonl#1",
            },
            {
                "account": capital.account,
                "provenance": capital,
                "total": Decimal("5.59"),
                "per_wallet": {"Spot": Decimal("5.59")},
                "source": "capital.jsonl#1",
                "source_kind": "quoted wallet reading",
            },
            {"spot"},
        )
