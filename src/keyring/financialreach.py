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
from .provenance import (
    Provenance,
    is_operator_observation,
    provenance_for,
    qualified_label,
    require_compatible_provenance,
)

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


def _layer(
    value: Any,
    label: str,
    reason: str,
    sources: list[str] | None = None,
    provenance_key: str | None = None,
) -> dict[str, Any]:
    layer = {"value": value, "label": label, "reason": reason, "sources": sources or []}
    if provenance_key:
        layer["provenance_key"] = provenance_key
    return layer


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


def _all_records(evidence_dir: str | Path) -> list[tuple[str, EvidenceRecord]]:
    records: list[tuple[str, EvidenceRecord]] = []
    for path in sorted(Path(evidence_dir).glob("*.jsonl")):
        records.extend((path.name, record) for record in EvidenceLog(path).records(verify=True))
    return records


def _gate_observations(
    records: list[tuple[str, EvidenceRecord]],
) -> list[dict[str, Any]]:
    """Return every gate observation with its account/client/mode context.

    The direct gateway baseline is a harness-captured probe rather than an
    operator observation.  It is included separately because it is a useful
    comparison path, but it is never allowed to overwrite a client result.
    """
    observations: list[dict[str, Any]] = []
    for filename, record in records:
        is_client_observation = (
            record.record_type == "operator_observation"
            and record.operation == "client_gate_observation"
        )
        is_direct_gateway_baseline = (
            record.record_type == "capability_probe"
            and record.run_id.startswith("full-proof-spot")
            and record.gate == "UNGATED"
        )
        if not (is_client_observation or is_direct_gateway_baseline):
            continue
        provenance = provenance_for(record, filename)
        observations.append(
            {
                "provenance": provenance.as_dict(),
                "provenance_key": provenance.key,
                "account": provenance.account,
                "client": provenance.client,
                "permission_mode": provenance.permission_mode,
                "gated": record.gate != "UNGATED",
                "gate": _gate_value(record),
                "outcome": record.outcome or "—",
                "label": qualified_label(record),
                "operator_observed": is_operator_observation(record),
                "source": f"{filename}#{record.sequence}",
            }
        )
    return observations


def _confirmation_gate_observed(
    evidence_dir: str | Path,
    records: list[tuple[str, EvidenceRecord]] | None = None,
) -> dict[str, Any]:
    """Return all gate observations without choosing one by file order.

    A scalar default-mode answer is only emitted when every observed default
    has the same result.  Conflicting clients therefore remain a conflict.
    """
    observations = _gate_observations(records or _all_records(evidence_dir))
    defaults = [item for item in observations if item["permission_mode"] == "default"]
    manual = [item for item in observations if item["permission_mode"] == "manual"]
    default_results = {item["gated"] for item in defaults}
    manual_results = {item["gated"] for item in manual}
    return {
        "default_mode_gated": next(iter(default_results)) if len(default_results) == 1 else None,
        "default_mode_observed": bool(defaults),
        "strict_mode_gated": next(iter(manual_results)) if len(manual_results) == 1 else None,
        "strict_mode_observed": bool(manual),
        "default_mode_conflict": len(default_results) > 1,
        "observations": observations,
    }


def _gate_value(record: EvidenceRecord) -> str | None:
    value = getattr(record.gate, "value", record.gate)
    return str(value) if value is not None else None


def _wallet_values(payload: Any) -> tuple[Decimal, dict[str, Decimal]] | None:
    if not isinstance(payload, list):
        return None
    per_wallet: dict[str, Decimal] = {}
    total = Decimal(0)
    try:
        for entry in payload:
            name = str(entry["walletName"])
            amount = _decimal(entry["balance"])
            if amount is None:
                return None
            per_wallet[name] = amount
            total += amount
    except (KeyError, TypeError, ValueError):
        return None
    return total, per_wallet


def _capital_candidates(
    records: list[tuple[str, EvidenceRecord]],
) -> list[dict[str, Any]]:
    """Collect account-level capital facts without joining clients together."""
    candidates: list[dict[str, Any]] = []
    for filename, record in records:
        values: tuple[Decimal, dict[str, Decimal]] | None = None
        source_kind = ""
        if (
            record.record_type == "financial_balance_quote"
            and str(record.metadata.get("quote_asset", "")).upper() == "USDT"
        ):
            values = _wallet_values(_record_payload(record))
            source_kind = "quoted wallet reading"
        elif record.state_after or record.state_before:
            snapshot = record.state_after or record.state_before
            if snapshot and snapshot.complete() and snapshot.components:
                component = snapshot.components.get("wallet_balances")
                values = _wallet_values(component)
                source_kind = "complete account snapshot"
        if values is None:
            continue
        total, per_wallet = values
        provenance = provenance_for(record, filename)
        candidates.append(
            {
                "account": provenance.account,
                "provenance": provenance,
                "total": total,
                "per_wallet": per_wallet,
                "source": f"{filename}#{record.sequence}",
                "source_kind": source_kind,
                "occurred_at": record.occurred_at,
                "quoted": record.record_type == "financial_balance_quote",
            }
        )
    return candidates


def _latest_capital_by_account(
    records: list[tuple[str, EvidenceRecord]],
) -> dict[str, dict[str, Any]]:
    """Prefer the latest quoted balance, otherwise the latest full snapshot."""
    selected: dict[str, dict[str, Any]] = {}
    for candidate in sorted(_capital_candidates(records), key=lambda item: item["occurred_at"]):
        current = selected.get(candidate["account"])
        if current is None or candidate["quoted"] > current["quoted"] or (
            candidate["quoted"] == current["quoted"]
            and candidate["occurred_at"] >= current["occurred_at"]
        ):
            selected[candidate["account"]] = candidate
    return selected


def _capital_layers_for_gate(
    gate: dict[str, Any],
    capital: dict[str, Any] | None,
    verified: set[str],
) -> dict[str, Any]:
    """Build a row whose capital and gate provenance refer to one context."""
    row_key = gate["provenance_key"]
    if capital is None:
        return {
            "capital_visible": None,
            "capital_reachable_by_trading": None,
            "autonomous_capital_at_risk": None,
            "capital_source": None,
            "capital_provenance_key": None,
        }

    # Wallet balances are account-level facts.  They may be projected into a
    # client/mode row only after the account has been checked to match.  The
    # row key is the gate's full provenance key; the original source key stays
    # visible for auditability.
    require_compatible_provenance(
        capital["provenance"],
        Provenance(gate["account"], gate["client"], gate["permission_mode"]),
        source_scope="account",
    )
    total = capital["total"]
    reached = [
        name
        for name, amount in capital["per_wallet"].items()
        if WALLET_CAPABILITY.get(name) in verified
    ]
    reachable = sum(
        (capital["per_wallet"][name] for name in reached), Decimal(0)
    )
    if gate["gated"]:
        autonomous_reason = (
            "the client showed a confirmation prompt before dispatch; the account-level "
            f"reachable balance is {reachable} USDT"
        )
        autonomous_value = Decimal(0)
    else:
        autonomous_reason = (
            "no confirmation was observed before dispatch; the account-level reachable "
            f"balance is {reachable} USDT"
        )
        autonomous_value = reachable
    return {
        "capital_visible": _layer(
            str(total),
            "OBSERVED",
            f"{capital['source_kind']} for {capital['account']}; account-level fact",
            [capital["source"]],
            row_key,
        ),
        "capital_reachable_by_trading": _layer(
            str(reachable),
            "OBSERVED",
            "account-level capital in wallets covered by the measured trading paths "
            f"({', '.join(sorted(reached)) or 'none'})",
            [capital["source"]],
            row_key,
        ),
        "autonomous_capital_at_risk": _layer(
            str(autonomous_value),
            "OBSERVED",
            autonomous_reason,
            [gate["source"], capital["source"]],
            row_key,
        ),
        "capital_source": {
            "ref": capital["source"],
            "kind": capital["source_kind"],
            "account": capital["account"],
            "provenance_key": row_key,
            "source_provenance_key": capital["provenance"].key,
            "scope": "account",
            "gate_context": gate["provenance_key"],
        },
        "capital_provenance_key": row_key,
    }


def _provenance_rows(
    records: list[tuple[str, EvidenceRecord]],
    verified: set[str],
) -> list[dict[str, Any]]:
    """Return one financial/gate row per observed account/client/mode."""
    gates = _gate_observations(records)
    capital_by_account = _latest_capital_by_account(records)
    rows: list[dict[str, Any]] = []
    for gate in gates:
        capital = None if gate["client"] == "Direct gateway" else capital_by_account.get(gate["account"])
        layers = _capital_layers_for_gate(gate, capital, verified)
        rows.append(
            {
                "provenance": gate["provenance"],
                "provenance_key": gate["provenance_key"],
                "account": gate["account"],
                "client": gate["client"],
                "permission_mode": gate["permission_mode"],
                "gate": gate["gate"],
                "gated": gate["gated"],
                "gate_label": gate["label"],
                "gate_source": gate["source"],
                "gate_operator_observed": gate["operator_observed"],
                **layers,
            }
        )
    return rows


def reach(evidence_dir: str | Path = "evidence/raw") -> dict[str, Any]:
    records = _all_records(evidence_dir)
    snapshot, record = latest_complete_snapshot(evidence_dir)
    authority = derive(evidence_dir)
    verified = {
        name for name, row in authority["capabilities"].items() if row["classification"] == "VERIFIED"
    }
    gate = _confirmation_gate_observed(evidence_dir, records)
    provenance_rows = _provenance_rows(records, verified)

    # The scalar layers below are retained for the terminal/API compatibility
    # of the original command, but they are selected only from one matching
    # account/client/mode context.  The dashboard renders provenance_rows and
    # never treats this compatibility view as an aggregate finding.
    capital_by_account = _latest_capital_by_account(records)
    capital_context = None
    if record is not None:
        capital_context = capital_by_account.get(provenance_for(record).account)
    if capital_context is None and capital_by_account:
        capital_context = max(
            capital_by_account.values(), key=lambda item: item["occurred_at"]
        )
    selected_gate = None
    if capital_context is not None:
        selected_gate = next(
            (
                item
                for item in gate["observations"]
                if item["account"] == capital_context["account"]
                and item["client"] == capital_context["provenance"].client
                and item["permission_mode"] == capital_context["provenance"].permission_mode
            ),
            None,
        )

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
            "provenance_rows": provenance_rows,
            "confirmation_gate": gate,
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
    elif selected_gate is None:
        autonomous = _layer(
            None,
            "INCONCLUSIVE",
            "no gate observation matches the account and client that supplied the capital figure",
        )
    elif selected_gate["gated"]:
        autonomous = _layer(
            "0",
            "OBSERVED",
            "a confirmation prompt was observed in the same account and client context as "
            "the capital figure",
            [selected_gate["source"]],
        )
    else:
        autonomous = _layer(
            str(reachable_total),
            "OBSERVED",
            "no confirmation prompt was observed in the same account and client context, "
            "so all reachable capital could move without a human approving it",
            [selected_gate["source"], "wallet_balances"],
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
        "confirmation_gate": {
            **gate,
            "selected_for_capital": selected_gate,
        },
        "provenance_rows": provenance_rows,
    }


def render(result: dict[str, Any]) -> str:
    def line(name: str, layer: dict[str, Any]) -> list[str]:
        value = layer["value"]
        shown = "INCONCLUSIVE" if value is None else str(value)
        out = [f"  {name:34}{shown:>16}   {layer['label']}"]
        out.append(f"      {layer['reason']}")
        return out

    lines = ["FINANCIAL REACH, LAYERED", "", "PROVENANCE-KEYED CLIENT / CAPITAL VIEWS", ""]
    for row in result.get("provenance_rows", []):
        lines.append(
            f"  {row['account']} / {row['client']} / {row['permission_mode']}"
        )
        lines.append(f"      gate                         {row['gate'] or '—'}   {row['gate_label']}")
        capital = row.get("capital_visible")
        reachable = row.get("capital_reachable_by_trading")
        autonomous = row.get("autonomous_capital_at_risk")
        if capital is None:
            lines.append("      capital                     —")
        else:
            lines.append(f"      capital                     {capital['value']} USDT   {capital['label']}")
            lines.append(
                f"      reachable                  {reachable['value']} USDT   {reachable['label']}"
            )
            lines.append(
                f"      autonomous                 {autonomous['value']} USDT   {autonomous['label']}"
            )
        lines.append(f"      gate evidence               {row['gate_source']}")
        lines.append("")

    lines.append("COMPATIBILITY VIEW (selected matching capital context)")
    lines.append("")
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
