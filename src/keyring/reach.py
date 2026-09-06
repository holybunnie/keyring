from __future__ import annotations

from typing import Any

import pandas as pd

from .labels import Classification, EvidenceLabel
from .models import ClassificationResult, StrategyConfig


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
    all_measured_capabilities = sorted(frame["capability"].tolist()) if not frame.empty else []
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
