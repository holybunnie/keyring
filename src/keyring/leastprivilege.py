"""F3 - the least-privilege diff.

What the strategy declares it needs, against what the grant was measured to
allow. The strategy's needs are read from its manifest and are never inferred
from a model.

Two kinds of excess are reported, and they are never added together:

* **Measured excess** - a capability this build probed and classified VERIFIED
  that the manifest declares it does not need. This is an OBSERVED claim.
* **Potential excess** - instruments the venue lists that the manifest does not
  need. This is the venue's listed surface, not measured reach, and is labelled
  as such. Part IX forbids presenting a listed instrument count as effective
  authority, so the two never merge into one number.

The remediation cost is read from the evidence log rather than asserted.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .authority import derive
from .config import load_strategy_config
from .evidence import EvidenceLog
from .models import StrategyConfig
from .reach import required_spot_symbols

# Which capability ids a manifest flag covers. `futures: false` declines both
# futures products; there is no separate manifest flag for each.
MANIFEST_FLAG_CAPABILITIES = {
    "margin": ("margin",),
    "futures": ("usd_m_futures", "coin_m_futures"),
    "transfer": ("transfer",),
}


def needed_capabilities(strategy: StrategyConfig) -> set[str]:
    """Capabilities the manifest declares it needs. Read, never inferred."""
    needed: set[str] = set()
    if required_spot_symbols(strategy):
        needed.add("spot")
    for flag, capabilities in MANIFEST_FLAG_CAPABILITIES.items():
        if getattr(strategy.needs, flag, False):
            needed.update(capabilities)
    return needed


def _instrument_inventory(evidence_dir: str | Path) -> dict[str, Any] | None:
    """The listed spot instrument inventory, from the evidence log."""
    for path in sorted(Path(evidence_dir).glob("*.jsonl")):
        for record in EvidenceLog(path).records(verify=True):
            if record.record_type == "instrument_inventory" and isinstance(record.response, dict):
                return record.response
    return None


def _remediation(evidence_dir: str | Path) -> dict[str, Any]:
    """The measured cost of narrowing a grant, from the evidence log."""
    for path in sorted(Path(evidence_dir).glob("*.jsonl")):
        for record in EvidenceLog(path).records(verify=True):
            if record.run_id == "m0-5-permission-mutability":
                return {
                    "outcome": record.outcome,
                    "label": "OBSERVED",
                    "source": record.source,
                    "evidence_type": record.metadata.get("evidence_type"),
                }
    return {"outcome": None, "label": "INCONCLUSIVE", "source": None, "evidence_type": None}


def diff(
    strategy_path: str | Path = "config/strategy.yaml",
    evidence_dir: str | Path = "evidence/raw",
) -> dict[str, Any]:
    """Diff the manifest against the measured fingerprint."""
    loaded = load_strategy_config(strategy_path)
    strategy: StrategyConfig = loaded.model
    authority = derive(evidence_dir)

    required_symbols = required_spot_symbols(strategy)
    needed = needed_capabilities(strategy)

    capabilities = authority["capabilities"]
    verified = {
        name for name, row in capabilities.items() if row["classification"] == "VERIFIED"
    }
    # Only VERIFIED capabilities count as measured excess. An INCONCLUSIVE one is
    # not evidence of authority, and a DENIED one is evidence of its absence.
    measured_excess = sorted(verified - needed)
    unmet = sorted(needed - verified)

    excess_write_tools = sorted(
        tool
        for name in measured_excess
        for tool in capabilities[name]["advertised_write_tools"]
    )

    inventory = _instrument_inventory(evidence_dir)
    if inventory:
        listed = inventory.get("trading_symbols", [])
        potential_excess = sorted(set(listed) - set(required_symbols))
        instruments = {
            "status": "POTENTIAL_SURFACE_ONLY",
            "label": "OBSERVED (venue listing), NOT measured reach",
            "listed_trading_instruments": inventory.get("trading_symbol_count"),
            "required_by_strategy": len(required_symbols),
            "potential_excess_count": len(potential_excess),
            "note": (
                "This is what the venue lists, not what this grant was measured to "
                "reach. Only the probed symbol has measured evidence. This count is "
                "never merged with measured excess."
            ),
        }
    else:
        instruments = {
            "status": "UNAVAILABLE",
            "label": "INCONCLUSIVE",
            "note": "no instrument inventory record is present in the evidence log",
        }

    return {
        "strategy": strategy.name,
        "strategy_config_sha256": loaded.sha256,
        "records_replayed": authority["records_replayed"],
        "granted_scope": authority["granted_scope"],
        "needed_capabilities": sorted(needed),
        "required_spot_symbols": required_symbols,
        "verified_capabilities": sorted(verified),
        "measured_excess_capabilities": measured_excess,
        "measured_excess_write_tools": excess_write_tools,
        "measured_excess_write_tool_count": len(excess_write_tools),
        "unmet_needs": unmet,
        "instruments": instruments,
        "remediation": _remediation(evidence_dir),
    }


def render(result: dict[str, Any]) -> str:
    lines = [
        f"LEAST-PRIVILEGE DIFF — {result['strategy']}",
        f"  derived from {result['records_replayed']} evidence records",
        f"  granted scope   {result['granted_scope']}",
        "",
        "NEEDED       (declared in the manifest, never inferred)",
        f"  capabilities   {', '.join(result['needed_capabilities']) or 'none'}",
        f"  instruments    {len(result['required_spot_symbols'])}"
        f"  ({', '.join(result['required_spot_symbols'])})",
        "",
        "EFFECTIVE    (measured, VERIFIED by probe with a passing control)",
        f"  capabilities   {', '.join(result['verified_capabilities']) or 'none'}",
        "",
        "EXCESS — MEASURED",
        f"  capabilities   {', '.join(result['measured_excess_capabilities']) or 'none'}",
        f"  write tools    {result['measured_excess_write_tool_count']}",
    ]
    for tool in result["measured_excess_write_tools"]:
        lines.append(f"    {tool}")

    instruments = result["instruments"]
    lines += ["", f"EXCESS — POTENTIAL  ({instruments['status']})"]
    if instruments["status"] == "POTENTIAL_SURFACE_ONLY":
        lines += [
            f"  venue lists    {instruments['listed_trading_instruments']} spot instruments trading",
            f"  strategy needs {instruments['required_by_strategy']}",
            f"  excess         {instruments['potential_excess_count']}  "
            f"— {instruments['label']}",
        ]
    else:
        lines.append(f"  {instruments['note']}")

    if result["unmet_needs"]:
        lines += ["", "UNMET NEEDS", f"  {', '.join(result['unmet_needs'])}"]

    remediation = result["remediation"]
    lines += [
        "",
        "REMEDIATION COST",
        f"  {remediation['outcome']}  — {remediation['label']}",
    ]
    if remediation["outcome"] == "RECONNECT_REQUIRED":
        lines.append("  An over-broad grant cannot be narrowed. It must be disconnected")
        lines.append("  and re-authorized from scratch.")
    return "\n".join(lines)
