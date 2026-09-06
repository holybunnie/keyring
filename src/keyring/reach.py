from __future__ import annotations

from typing import Any

import pandas as pd

from .labels import Classification, EvidenceLabel
from .models import ClassificationResult, EvidenceRecord, StrategyConfig


def required_spot_symbols(strategy: StrategyConfig) -> list[str]:
    spot = strategy.needs.trade.get("spot", {})
    symbols = spot.get("symbols", []) if isinstance(spot, dict) else []
    return [str(symbol).upper() for symbol in symbols]


def least_privilege_diff(
    strategy: StrategyConfig,
    classifications: list[ClassificationResult],
    *,
    measured_spot_symbols: list[str] | None = None,
    potential_spot_symbols: list[str] | None = None,
) -> dict[str, Any]:
    required = required_spot_symbols(strategy)
    verified = {item.capability for item in classifications if item.classification == Classification.VERIFIED}
    denied = {item.capability for item in classifications if item.classification == Classification.DENIED}
    advertised_only = {item.capability for item in classifications if item.classification == Classification.ADVERTISED_ONLY}
    unresolved = {item.capability for item in classifications if item.classification == Classification.INCONCLUSIVE}

    frame = pd.DataFrame(
        [
            {"capability": item.capability, "classification": item.classification.value, "reason": item.reason}
            for item in classifications
        ]
    )
    tested_capabilities = sorted(
        item.capability for item in classifications if item.evidence_sequences
    )
    all_measured_capabilities = sorted(
        item.capability
        for item in classifications
        if item.evidence_sequences and item.classification != Classification.INCONCLUSIVE
    )
    measured_symbols = sorted({symbol.upper() for symbol in (measured_spot_symbols or [])})
    potential_symbols = sorted({symbol.upper() for symbol in (potential_spot_symbols or [])})

    if measured_spot_symbols is not None:
        excess_symbols = sorted(set(measured_symbols) - set(required))
        symbol_status = "MEASURED"
        symbol_label = EvidenceLabel.OBSERVED.value
    elif potential_spot_symbols is not None:
        excess_symbols = sorted(set(potential_symbols) - set(required))
        symbol_status = "POTENTIAL_SURFACE_ONLY"
        symbol_label = EvidenceLabel.DOCUMENTED.value
    else:
        excess_symbols = []
        symbol_status = "UNAVAILABLE"
        symbol_label = EvidenceLabel.OBSERVED.value

    return {
        "strategy": strategy.name,
        "required_spot_symbols": required,
        "required_spot_symbol_count": len(required),
        "measured_capabilities": all_measured_capabilities,
        "tested_capabilities": tested_capabilities,
        "verified_capabilities": sorted(verified),
        "denied_capabilities": sorted(denied),
        "advertised_only_capabilities": sorted(advertised_only),
        "inconclusive_capabilities": sorted(unresolved),
        "spot_symbol_status": symbol_status,
        "spot_symbol_label": symbol_label,
        "spot_symbols": measured_symbols if measured_spot_symbols is not None else potential_symbols,
        "spot_symbol_count": len(measured_symbols if measured_spot_symbols is not None else potential_symbols),
        "excess_spot_symbols": excess_symbols,
        "excess_spot_symbol_count": len(excess_symbols),
        "note": "Effective authority is not inferred from a potential surface.",
    }


def _capital_field(value: Any, label: str, reason: str) -> dict[str, Any]:
    return {"value": value, "label": label, "reason": reason}


def layered_capital_view(
    records: list[EvidenceRecord],
    classifications: list[ClassificationResult],
) -> dict[str, dict[str, Any]]:
    """Return only capital layers backed by explicit evidence links."""
    account_records = [record for record in records if record.record_type == "account_snapshot"]
    latest_account = account_records[-1] if account_records else None
    balances = None
    if latest_account and isinstance(latest_account.response, dict):
        balances = latest_account.response.get("balances")
    visible = (
        _capital_field(balances, latest_account.label.value, "latest account snapshot")
        if balances is not None and latest_account
        else _capital_field(None, "INCONCLUSIVE", "no account snapshot with balances is present")
    )

    spot_result = next((item for item in classifications if item.capability == "spot"), None)
    spot_record = next(
        (record for record in reversed(records) if record.record_type == "probe" and record.capability == "spot"),
        None,
    )
    linked = bool(spot_record and spot_record.metadata.get("capital_state_linked") is True)
    reachable = (
        _capital_field(balances, "OBSERVED", "verified spot probe linked to the account snapshot")
        if spot_result and spot_result.classification == Classification.VERIFIED and linked and balances is not None
        else _capital_field(None, "INCONCLUSIVE", "trading reach is not linked to a verified account snapshot")
    )

    if spot_record and spot_record.gate in {"CLIENT-GATED", "SERVER-GATED"}:
        autonomous = _capital_field(0, "OBSERVED", "a confirmation gate was observed")
    else:
        autonomous = _capital_field(None, "INCONCLUSIVE", "autonomous execution was not observed")

    walk_cost = None
    if spot_record and spot_record.metadata.get("walk_cost") is not None:
        walk_cost = _capital_field(spot_record.metadata["walk_cost"], "OBSERVED", "walk cost supplied by the evidence record")
    else:
        walk_cost = _capital_field(None, "INCONCLUSIVE", "live-book exit cost is not present")

    return {
        "capital_visible": visible,
        "capital_reachable_by_trading": reachable,
        "autonomous_capital_at_risk": autonomous,
        "immediate_exit_cost": walk_cost,
    }
