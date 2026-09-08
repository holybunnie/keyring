"""F2 - financial reach, layered.

One number would be dishonest, because these are different quantities:

* what capital is visible
* what capital a measured trading capability can reach
* what capital could move without a human approving it
* what it would cost to exit holdings immediately

Each layer carries its own label, its own reason, and the snapshot components it
was derived from. A layer whose inputs are missing is INCONCLUSIVE, never zero:
absence of evidence is not a measurement of zero.

Two refusals are deliberate:

* The futures gross notional ceiling is not computed. Leverage brackets, margin
  mode and existing positions all bear on it and none is resolved here.
* Reachable instruments are reported as probed-versus-listed. A listed
  instrument count is not measured reach (Part IX).
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
from typing import Any

from .authority import derive
from .evidence import EvidenceLog
from .models import EvidenceRecord, StateSnapshot

# Which wallet a capability's capital sits in, as OBSERVED in the
# wallet.queryUserWalletBalance payload.
WALLET_CAPABILITY = {
    "Spot": "spot",
    "USDⓈ-M Futures": "usd_m_futures",
    "COIN-M Futures": "coin_m_futures",
    "Cross Margin": "margin",
    "Isolated Margin": "margin",
}


def _decimal(value: Any) -> Decimal | None:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _layer(value: Any, label: str, reason: str, sources: list[str] | None = None) -> dict[str, Any]:
    return {"value": value, "label": label, "reason": reason, "sources": sources or []}


def _unavailable(component: Any) -> bool:
    return isinstance(component, dict) and component.get("unavailable") is True


def _record_payload(record: EvidenceRecord) -> Any:
    """Decode a retained JSON-RPC response without trusting derived fields."""
    if record.response is not None:
        return record.response
    if not record.raw_response:
        return None
    try:
        envelope = json.loads(record.raw_response)
    except (TypeError, ValueError):
        return None
    result = envelope.get("result", {}) if isinstance(envelope, dict) else {}
    content = result.get("content") if isinstance(result, dict) else None
    if isinstance(content, list) and content and isinstance(content[0], dict):
        text = content[0].get("text")
        if isinstance(text, str):
            try:
                return json.loads(text)
            except (TypeError, ValueError):
                return text
    return result


def _latest_quoted_wallet_balances(
    evidence_dir: str | Path,
    quote_asset: str = "USDT",
) -> tuple[Decimal, dict[str, Decimal], EvidenceRecord] | None:
    """Return the newest wallet reading explicitly quoted in ``quote_asset``."""
    latest: tuple[Decimal, dict[str, Decimal], EvidenceRecord] | None = None
    for path in sorted(Path(evidence_dir).glob("*.jsonl")):
        for record in EvidenceLog(path).records(verify=True):
            if record.record_type != "financial_balance_quote":
                continue
            if str(record.metadata.get("quote_asset", "")).upper() != quote_asset.upper():
                continue
            payload = _record_payload(record)
            if not isinstance(payload, list):
                continue
            per_wallet: dict[str, Decimal] = {}
            total = Decimal(0)
            try:
                for entry in payload:
                    name = str(entry["walletName"])
                    amount = _decimal(entry["balance"])
                    if amount is None:
                        raise ValueError("wallet balance is not numeric")
                    per_wallet[name] = amount
                    total += amount
            except (KeyError, TypeError, ValueError):
                continue
            latest = (total, per_wallet, record)
    return latest


def _latest_order_book_walk(
    evidence_dir: str | Path,
) -> tuple[Decimal, EvidenceRecord, dict[str, Any]] | None:
    """Return the newest retained, source-backed exit-cost calculation."""
    latest: tuple[Decimal, EvidenceRecord, dict[str, Any]] | None = None
    for path in sorted(Path(evidence_dir).glob("*.jsonl")):
        for record in EvidenceLog(path).records(verify=True):
            if record.record_type != "order_book_walk":
                continue
            payload = _record_payload(record)
            if not isinstance(payload, dict):
                continue
            value = _decimal(payload.get("exit_cost_usdt"))
            if value is None:
                continue
            latest = (value, record, payload)
    return latest


def latest_complete_snapshot(
    evidence_dir: str | Path = "evidence/raw",
) -> tuple[StateSnapshot | None, EvidenceRecord | None]:
    """The most recent snapshot that satisfies the Law 3 completeness rule."""
    best: tuple[StateSnapshot, EvidenceRecord] | None = None
    for path in sorted(Path(evidence_dir).glob("*.jsonl")):
        for record in EvidenceLog(path).records(verify=True):
            snapshot = record.state_after or record.state_before
            if snapshot and snapshot.components and snapshot.complete():
                best = (snapshot, record)
    return best if best else (None, None)


def _confirmation_gate_observed(evidence_dir: str | Path) -> dict[str, Any]:
    """What the evidence says about a confirmation step, in the tested default."""
    default_mode, strict_mode = None, None
    for path in sorted(Path(evidence_dir).glob("*.jsonl")):
        for record in EvidenceLog(path).records(verify=True):
            if record.record_type != "operator_observation":
                continue
            mode = str(record.metadata.get("permission_mode", ""))
            if record.operation != "client_gate_observation":
                continue
            if "manual" in mode:
                strict_mode = record
            else:
                default_mode = record
    return {
        "default_mode_gated": bool(default_mode and default_mode.gate != "UNGATED"),
        "default_mode_observed": default_mode is not None,
        "strict_mode_gated": bool(strict_mode and strict_mode.gate != "UNGATED"),
        "strict_mode_observed": strict_mode is not None,
    }


def reach(evidence_dir: str | Path = "evidence/raw") -> dict[str, Any]:
    snapshot, record = latest_complete_snapshot(evidence_dir)
    authority = derive(evidence_dir)
    verified = {
        name for name, row in authority["capabilities"].items() if row["classification"] == "VERIFIED"
    }
    gate = _confirmation_gate_observed(evidence_dir)

    if snapshot is None:
        missing = _layer(None, "INCONCLUSIVE", "no complete state snapshot exists in the evidence log")
        return {
            "capital_visible": missing,
            "capital_reachable_by_trading": missing,
            "autonomous_capital_at_risk": missing,
            "immediate_exit_cost": missing,
            "open_positions": missing,
            "instruments": missing,
            "futures_gross_notional_ceiling": missing,
        }

    components = snapshot.components

    # --- capital visible -----------------------------------------------------
    wallets = components.get("wallet_balances")
    quoted = _latest_quoted_wallet_balances(evidence_dir)
    if quoted is not None:
        total, per_wallet, quoted_record = quoted
        visible = _layer(
            str(total),
            "OBSERVED",
            "sum of wallet balances from a retained wallet reading explicitly quoted in USDT",
            [f"record:{quoted_record.sequence}"],
        )
    elif _unavailable(wallets) or not isinstance(wallets, list):
        visible = _layer(None, "INCONCLUSIVE", "wallet balance component unavailable")
        per_wallet: dict[str, Decimal] = {}
    else:
        per_wallet = {}
        total = Decimal(0)
        undecodable = []
        for entry in wallets:
            amount = _decimal(entry.get("balance"))
            name = entry.get("walletName", "?")
            if amount is None:
                undecodable.append(name)
                continue
            per_wallet[name] = amount
            total += amount
        if undecodable:
            visible = _layer(
                None, "INCONCLUSIVE", f"balance not decodable for: {', '.join(undecodable)}"
            )
        else:
            visible = _layer(
                str(total),
                "OBSERVED",
                "sum of every wallet balance in the latest complete snapshot; denominated "
                "as the API returned it, with no quoteAsset requested",
                ["wallet_balances"],
            )

    # --- capital reachable by a measured trading capability ------------------
    if visible["label"] != "OBSERVED":
        reachable = _layer(None, "INCONCLUSIVE", "capital visible is unresolved")
        reachable_total = None
    else:
        reachable_total = Decimal(0)
        reached: list[str] = []
        for name, amount in per_wallet.items():
            capability = WALLET_CAPABILITY.get(name)
            if capability and capability in verified:
                reachable_total += amount
                reached.append(name)
        reachable = _layer(
            str(reachable_total),
            "OBSERVED",
            "capital held in wallets whose trading capability was probed and classified "
            f"VERIFIED ({', '.join(sorted(reached)) or 'none'})",
            ["wallet_balances"],
        )

    # --- autonomous capital at risk -----------------------------------------
    # The reason matters as much as the number. A zero here must not be
    # attributed to a confirmation gate unless a gate was actually observed.
    if reachable_total is None:
        autonomous = _layer(None, "INCONCLUSIVE", "reachable capital is unresolved")
    elif not gate["default_mode_observed"]:
        autonomous = _layer(
            None, "INCONCLUSIVE", "no client gate observation exists in the evidence log"
        )
    elif gate["default_mode_gated"]:
        autonomous = _layer(
            "0",
            "OBSERVED",
            "a confirmation step was observed in the tested client default",
        )
    else:
        autonomous = _layer(
            str(reachable_total),
            "OBSERVED",
            "no confirmation step was observed in the tested client default, so all "
            "reachable capital could move without a human approving it. This figure is "
            "currently zero because the account is empty, NOT because a gate exists.",
            ["wallet_balances"],
        )

    # --- holdings and immediate exit cost ------------------------------------
    account = components.get("spot_account")
    if _unavailable(account) or not isinstance(account, dict):
        holdings = _layer(None, "INCONCLUSIVE", "spot account component unavailable")
        exit_cost = _layer(None, "INCONCLUSIVE", "holdings are unresolved")
    else:
        non_zero = [
            b
            for b in account.get("balances", [])
            if (_decimal(b.get("free")) or 0) != 0 or (_decimal(b.get("locked")) or 0) != 0
        ]
        holdings = _layer(
            len(non_zero), "OBSERVED", "spot balances with a non-zero free or locked amount",
            ["spot_account"],
        )
        walk = _latest_order_book_walk(evidence_dir)
        if non_zero and walk is not None:
            value, walk_record, walk_payload = walk
            exit_cost = _layer(
                str(value),
                "OBSERVED",
                "live BTCUSDT bids were walked for the post-buy BTC holding; value includes "
                f"the estimated taker fee across {walk_payload.get('levels_consumed', '?')} "
                "order-book level(s)",
                [f"record:{walk_record.sequence}"],
            )
        elif non_zero:
            exit_cost = _layer(
                None,
                "INCONCLUSIVE",
                "holdings exist but no order-book walk was performed; an exit cost is not "
                "asserted without one",
            )
        else:
            exit_cost = _layer(
                "0",
                "OBSERVED",
                "there are no holdings to exit, so the cost is zero by absence rather than "
                "by an order-book walk",
                ["spot_account"],
            )

    # --- open positions ------------------------------------------------------
    position_counts: dict[str, Any] = {}
    for key in ("usds_positions", "coinm_positions"):
        component = components.get(key)
        if _unavailable(component) or not isinstance(component, list):
            position_counts[key] = "INCONCLUSIVE"
            continue
        position_counts[key] = sum(
            1 for p in component if (_decimal(p.get("positionAmt")) or 0) != 0
        )
    unresolved_positions = [k for k, v in position_counts.items() if v == "INCONCLUSIVE"]
    positions = _layer(
        position_counts,
        "INCONCLUSIVE" if unresolved_positions else "OBSERVED",
        f"components unavailable: {', '.join(unresolved_positions)}"
        if unresolved_positions
        else "positions with a non-zero amount across both futures products",
        ["usds_positions", "coinm_positions"],
    )

    # --- instruments ---------------------------------------------------------
    probed = sorted(
        name
        for name, row in authority["capabilities"].items()
        if row["classification"] == "VERIFIED" and row["probe_tool"]
    )
    listed = None
    for path in sorted(Path(evidence_dir).glob("*.jsonl")):
        for rec in EvidenceLog(path).records(verify=True):
            if rec.record_type == "instrument_inventory" and isinstance(rec.response, dict):
                listed = rec.response.get("trading_symbol_count")
    instruments = {
        "capabilities_verified": probed,
        "spot_symbols_probed": 1 if "spot" in verified else 0,
        "spot_symbols_listed_trading": listed,
        "label": "OBSERVED (probed) / OBSERVED venue listing (listed)",
        "reason": (
            "Reach is reported as probed versus listed. A listed instrument count is the "
            "venue's surface, not measured reach, and the two are never merged."
        ),
    }

    return {
        "derived_from_record": record.run_id if record else None,
        "state_digest": snapshot.digest,
        "capital_visible": visible,
        "capital_reachable_by_trading": reachable,
        "autonomous_capital_at_risk": autonomous,
        "spot_holdings": holdings,
        "immediate_exit_cost": exit_cost,
        "open_positions": positions,
        "instruments": instruments,
        "futures_gross_notional_ceiling": _layer(
            None,
            "INCONCLUSIVE",
            "leverage brackets, margin mode and account limits are not resolved; a gross "
            "notional ceiling is not derivable from this evidence and is not asserted",
        ),
        "confirmation_gate": gate,
    }


def render(result: dict[str, Any]) -> str:
    def line(name: str, layer: dict[str, Any]) -> list[str]:
        value = layer["value"]
        shown = "INCONCLUSIVE" if value is None else str(value)
        out = [f"  {name:34}{shown:>16}   {layer['label']}"]
        out.append(f"      {layer['reason']}")
        return out

    lines = ["FINANCIAL REACH, LAYERED", ""]
    for name, key in [
        ("Capital visible", "capital_visible"),
        ("Capital reachable by trading", "capital_reachable_by_trading"),
        ("Autonomous capital at risk", "autonomous_capital_at_risk"),
        ("Spot holdings (non-zero assets)", "spot_holdings"),
        ("Immediate exit cost", "immediate_exit_cost"),
        ("Futures gross notional ceiling", "futures_gross_notional_ceiling"),
    ]:
        lines += line(name, result[key])
        lines.append("")

    positions = result["open_positions"]
    lines.append(f"  {'Open futures positions':34}{str(positions['value']):>16}   {positions['label']}")
    lines.append(f"      {positions['reason']}")
    lines.append("")

    instruments = result["instruments"]
    lines.append("  INSTRUMENTS")
    lines.append(f"      capabilities verified        {', '.join(instruments['capabilities_verified'])}")
    lines.append(f"      spot symbols probed          {instruments['spot_symbols_probed']}")
    lines.append(f"      spot symbols listed trading  {instruments['spot_symbols_listed_trading']}")
    lines.append(f"      {instruments['reason']}")
    return "\n".join(lines)
