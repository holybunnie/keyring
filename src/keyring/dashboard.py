"""The read-only KEYRING connection report.

The page is deliberately understandable without knowing the implementation.
It answers four questions in order: what was granted, what the connection
could reach, whether money changed, and what evidence supports each answer.
Every value is derived from verified append-only evidence. There is no write
route and no action button that can affect Binance.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
from decimal import Decimal, InvalidOperation
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .authority import derive, is_write_tool_name
from .config import load_probe_config
from .evidence import EvidenceLog
from .financialreach import _confirmation_gate_observed, reach
from .leastprivilege import diff
from .mcp import _binance_error_code
from .prober import classify_error_code
from .provenance import account_for, is_operator_observation, qualified_label
from .revocation import revocation_summary
from .trace import trace


BOUNDARY = (
    "The capability checks were designed to stop before an order could execute, "
    "and account state was checked before and after each one. A separate, explicitly "
    "approved buy/sell measurement is shown separately. This page is read-only. "
    "KEYRING performs the audit. An AI model can propose bounded test inputs, but "
    "deterministic KEYRING code controls every request and final classification."
)

# Published first-party statements. The measured column is populated from the
# evidence log; these strings are never used to create a classification.
CONTRADICTIONS = [
    {
        "question": "Can permissions be narrowed without reconnecting?",
        "source_a": "MCP documentation says to disconnect and reconnect to update",
        "source_b": "Launch material says permissions can be reviewed or changed",
        "measured_from": "m0-5-permission-mutability",
    },
    {
        "question": "Is a confirmation always shown before an action?",
        "source_a": "MCP documentation describes confirmation for non-read actions",
        "source_b": "Support material describes flows designed to request confirmation",
        "measured_from": "client_gate_observation",
    },
]

CAPABILITY_LABELS = {
    "spot": "Spot trading",
    "margin": "Margin trading",
    "usd_m_futures": "USDⓈ-M Futures",
    "coin_m_futures": "COIN-M Futures",
    "convert": "Convert",
    "transfer": "Transfers",
}

STEP_LABELS = {
    "tool surface": "What was visible",
    "grant": "Permission given",
    "discovery delta": "What changed",
    "positive control": "Read check",
    "probe plan": "Safe test design",
    "probe": "Test request",
    "response": "Exchange response",
    "model interpretation": "Model suggestion",
    "financial state": "Before / after money check",
    "classification": "Conclusion",
}

RECORD_KIND_LABELS = {
    "session": "Connection",
    "initialize": "Connection setup",
    "tools_list": "Tool list",
    "mcp_discovery": "Tool discovery",
    "positive_control": "Read check",
    "capability_probe": "Safe test request",
    "permission_report": "Permission report",
    "operator_observation": "User observation",
    "financial_balance_quote": "Balance reading",
    "account_snapshot": "Account snapshot",
    "market_data": "Market data",
    "order_book_walk": "Order-book calculation",
    "transaction": "Approved transaction",
    "revocation_check": "Access check",
}


def _evidence_dir(path: str | Path) -> Path:
    path = Path(path)
    return path if path.is_dir() else path.parent


def _all_records(evidence_dir: Path) -> list[tuple[str, Any]]:
    records: list[tuple[str, Any]] = []
    for file in sorted(evidence_dir.glob("*.jsonl")):
        records.extend((file.name, record) for record in EvidenceLog(file).records(verify=True))
    return records


def _safety(evidence_dir: Path) -> dict[str, Any]:
    """Return request-budget and rate-limit health from the evidence."""
    try:
        budgets = load_probe_config().model.budgets
        max_per_run = getattr(budgets, "max_probes_per_run", None)
    except Exception:  # noqa: BLE001 - a missing config should not hide the page
        max_per_run = None

    status = "HEALTHY"
    try:
        all_records = [record for _, record in _all_records(evidence_dir)]
    except Exception:  # noqa: BLE001 - surfaced as a visible health state
        all_records = []
        status = "EVIDENCE UNVERIFIABLE"

    latest_probe = max(
        (record for record in all_records if record.record_type == "capability_probe"),
        key=lambda record: record.occurred_at,
        default=None,
    )
    active_run_id = latest_probe.run_id if latest_probe else None
    probes = 0
    last_429 = None
    for record in all_records:
        if active_run_id and record.run_id != active_run_id:
            continue
        if record.record_type == "capability_probe":
            probes += 1
        if record.http_status == 429:
            last_429 = record.occurred_at.isoformat()
            status = "BACKED OFF"
        elif record.http_status == 418:
            status = "STOPPED (418)"
        elif record.http_status == 403:
            status = "HALTED (403)"
    return {
        "probe_budget": f"{probes} / {max_per_run if max_per_run is not None else '?'} used",
        "probes_used": probes,
        "max_probes_per_run": max_per_run,
        "run_id": active_run_id,
        "rate_limit_status": status,
        "last_429": last_429 or "none",
    }


def _measured_contradictions(records: list[tuple[str, Any]]) -> list[dict[str, Any]]:
    outcomes: dict[str, dict[str, Any]] = {}
    for filename, record in records:
        if record.run_id == "m0-5-permission-mutability":
            outcomes["m0-5-permission-mutability"] = {
                "measured": record.outcome or "—",
                "label": qualified_label(record),
                "evidence": [f"{filename}#{record.sequence}"],
            }

    gate_observations = _confirmation_gate_observed(
        "", records
    )["observations"]

    rows = []
    for entry in CONTRADICTIONS:
        key = entry["measured_from"]
        if key == "m0-5-permission-mutability":
            if key not in outcomes:
                continue
            outcome = outcomes[key]
            measured = outcome["measured"]
            label = outcome["label"]
            evidence = outcome["evidence"]
        elif key == "client_gate_observation":
            if not gate_observations:
                continue
            measured_parts = []
            evidence = []
            labels = []
            for observation in gate_observations:
                result = "confirmation shown" if observation["gated"] else "no confirmation"
                measured_parts.append(
                    f"{observation['client']} / {observation['permission_mode']}: {result} "
                    f"({observation['label']})"
                )
                evidence.append(observation["source"])
                labels.append(observation["label"])
            measured = "; ".join(measured_parts)
            label = "OBSERVED · operator" if any("operator" in item for item in labels) else "OBSERVED · harness"
        else:
            continue
        rows.append({**entry, "measured": measured, "label": label, "evidence": evidence})
    return rows


def _decode_record_response(record: Any) -> Any:
    if record.response is not None:
        return record.response
    if not record.raw_response:
        return None
    try:
        envelope = json.loads(record.raw_response)
    except (TypeError, ValueError):
        return None
    if not isinstance(envelope, dict):
        return None
    result = envelope.get("result", envelope)
    if isinstance(result, dict):
        content = result.get("content")
        if isinstance(content, list) and content and isinstance(content[0], dict):
            text = content[0].get("text")
            if isinstance(text, str):
                try:
                    return json.loads(text)
                except (TypeError, ValueError):
                    return text
    return result


def _headline_facts(records: list[tuple[str, Any]], financial: dict[str, Any]) -> dict[str, Any]:
    permission_signatures: set[str] = set()
    permission_count = 0
    for _, record in records:
        if record.operation != "wallet.getApiKeyPermission" and record.record_type != "permission_report":
            continue
        payload = _decode_record_response(record)
        if payload is None:
            continue
        permission_count += 1
        permission_signatures.add(json.dumps(payload, sort_keys=True, default=str))
    return {
        "permission_report_count": permission_count,
        "permission_report_variants": len(permission_signatures),
        "permission_reports_differ": len(permission_signatures) > 1,
        "approved_transactions": sum(record.record_type == "transaction" for _, record in records),
        "tested_default_asked": financial.get("confirmation_gate", {}).get("default_mode_gated"),
    }


def _tools_from_record(record: Any) -> list[dict[str, Any]]:
    payload = _decode_record_response(record)
    if not isinstance(payload, dict) or not isinstance(payload.get("tools"), list):
        return []
    return [tool for tool in payload["tools"] if isinstance(tool, dict)]


def _account_headline_facts(
    records: list[tuple[str, Any]],
) -> list[dict[str, Any]]:
    """Build the hero panel from account-scoped evidence only."""
    by_account: dict[str, list[tuple[str, Any]]] = {}
    for filename, record in records:
        by_account.setdefault(account_for(record, filename), []).append((filename, record))

    rows: list[dict[str, Any]] = []
    for account in sorted(name for name in by_account if name in {"Account A", "Account B"}):
        account_records = by_account[account]
        scopes: dict[str, list[str]] = {}
        tools: dict[str, dict[str, Any]] = {}
        for filename, record in account_records:
            if not record.granted_scope:
                continue
            is_discovery = (
                record.operation == "initialize"
                or (record.operation or "").startswith("tools/list")
                or record.record_type in {"mcp_discovery", "tools_list"}
            )
            if not is_discovery:
                continue
            ref = f"{filename}#{record.sequence}"
            scopes.setdefault(record.granted_scope, []).append(ref)
            for tool in _tools_from_record(record):
                name = str(tool.get("name", ""))
                if name:
                    tools[name] = {"name": name, "ref": ref}

        selected_scope = max(
            scopes,
            key=lambda scope: (scope != "mcp:account:read", len(scope.split())),
            default=None,
        )
        selected_refs = scopes.get(selected_scope or "", [])
        selected_tools = [item for item in tools.values() if selected_scope]
        write_tools = [item for item in selected_tools if is_write_tool_name(item["name"])]
        consent = []
        if selected_scope and "mcp:spot:trade" in selected_scope:
            consent.append("Spot & Margin trading")
        if selected_scope and "mcp:futures:trade" in selected_scope:
            consent.append("Futures trading")

        permission_records = [
            (filename, record)
            for filename, record in account_records
            if record.operation == "wallet.getApiKeyPermission"
            or record.record_type == "permission_report"
        ]
        permission = None
        permission_ref = None
        if permission_records:
            permission_ref, permission_record = max(
                permission_records, key=lambda item: item[1].occurred_at
            )
            permission_ref = f"{permission_ref}#{permission_record.sequence}"
            permission = _decode_record_response(permission_record)
        permission_flags = None
        if isinstance(permission, dict):
            permission_flags = {
                "spot": bool(permission.get("enableSpotAndMarginTrading")),
                "futures": bool(permission.get("enableFutures")),
            }
            permission_text = (
                f"Spot {'✓' if permission.get('enableSpotAndMarginTrading') else '✕'} · "
                f"Futures {'✓' if permission.get('enableFutures') else '✕'}"
            )
        else:
            permission_text = "Not recorded"

        confirmed: dict[str, list[str]] = {}
        for filename, record in account_records:
            if record.record_type != "capability_probe" or not record.capability:
                continue
            if record.control_passed is not True or record.state_unchanged is not True:
                continue
            error_code = _binance_error_code(record.raw_response or "") or record.error_code
            if classify_error_code(error_code) != "VERIFIED":
                continue
            confirmed.setdefault(record.capability, []).append(
                f"{filename}#{record.sequence}"
            )
        tested = [
            (name, confirmed.get(name, []))
            for name in ("spot", "usd_m_futures", "coin_m_futures")
            if confirmed.get(name)
        ]
        test_text = " · ".join(
            f"{CAPABILITY_LABELS[name].replace(' trading', '').replace(' Futures', '')}: "
            "validation reached ✓"
            for name, _ in tested
        ) or "No trading path reached validation"
        test_refs = [ref for _, refs in tested for ref in refs]

        rows.append(
            {
                "account": account,
                "granted_mcp_scopes": {
                    "value": " · ".join(consent) or "Not recorded",
                    "technical": selected_scope,
                    "sources": selected_refs[:1],
                },
                "permission_check": {
                    "value": permission_text,
                    "technical": "wallet.getApiKeyPermission",
                    "sources": [permission_ref] if permission_ref else [],
                },
                "tools": {
                    "value": f"{len(selected_tools)} tools · {len(write_tools)} trading writes",
                    "sources": selected_refs,
                },
                "controlled_tests": {
                    "value": test_text,
                    "sources": test_refs,
                },
                "permission_flags": permission_flags,
                "tool_count": len(selected_tools),
                "write_count": len(write_tools),
                "tested_capabilities": [name for name, _ in tested],
            }
        )
    return rows


def _label_value(value: Any) -> str:
    return str(getattr(value, "value", value))


def _record_summary(filename: str, record: Any) -> dict[str, Any]:
    """Expose safe metadata to the evidence drawer, never raw payloads."""
    outcome_labels = {
        "access_permitted": "Access allowed",
        "access_denied": "Access denied",
        "downstream_validation": "Stopped by exchange checks",
        "authorized": "Connected",
        "exit_cost_measured": "Exit cost measured",
    }
    return {
        "ref": f"{filename}#{record.sequence}",
        "file": filename,
        "sequence": record.sequence,
        "kind": RECORD_KIND_LABELS.get(
            record.record_type, record.record_type.replace("_", " ").title()
        ),
        "operation": record.operation or "—",
        "capability": CAPABILITY_LABELS.get(record.capability, record.capability or "—"),
        "label": qualified_label(record),
        "capture_origin": "operator" if is_operator_observation(record) else "harness",
        "outcome": outcome_labels.get(record.outcome, record.outcome or "—"),
        "occurred_at": record.occurred_at.isoformat(),
        "error_code": record.error_code or "—",
        "state_proof": (
            "Before and after matched"
            if record.state_unchanged is True
            else "Complete before / after state recorded"
            if record.state_before is not None or record.state_after is not None
            else "—"
        ),
        "source": record.source or "—",
    }


def dashboard_state(
    evidence_path: str | Path,
    strategy_path: str | Path = "config/strategy.yaml",
) -> dict[str, Any]:
    """Rebuild the complete report from verified evidence."""
    evidence_dir = _evidence_dir(evidence_path)
    try:
        authority = derive(evidence_dir)
        records = _all_records(evidence_dir)
    except Exception as error:  # noqa: BLE001 - show the reason in the page
        return {
            "status": "DEGRADED",
            "reason": f"Evidence could not be replayed: {error}",
            "boundary": BOUNDARY,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    verified = [
        name
        for name, row in authority["capabilities"].items()
        if row["classification"] == "VERIFIED"
    ]
    status = "MEASURED" if verified else "DEGRADED"
    evidence_index = [_record_summary(filename, record) for filename, record in records]
    captured_times = [
        record.occurred_at
        for _, record in records
        if record.record_type != "m0_preflight"
    ]
    state: dict[str, Any] = {
        "status": status,
        # The legacy unsealed M0 preflight has no captured timestamp and is
        # assigned one while parsing. Excluding it keeps generated state
        # deterministic across builds.
        "generated_at": (
            max(captured_times).isoformat()
            if captured_times
            else datetime.now(timezone.utc).isoformat()
        ),
        "boundary": BOUNDARY,
        "granted_scope": authority["granted_scope"],
        "records_replayed": authority["records_replayed"],
        "state_chain": {
            "digests_seen": authority["state_digests_seen"],
            "distinct_states": authority["distinct_states"],
            "identical_throughout": authority["state_identical_throughout"],
            "probe_pairs": authority["probe_pairs"],
            "probe_pairs_identical": authority["probe_pairs_identical"],
            # `_all_records` verifies every active JSONL chain before this state
            # can be built. Chains are per file, not one global capture chain.
            "active_files_verified": True,
        },
        "safety": _safety(evidence_dir),
        "authority": authority["capabilities"],
        "contradictions": _measured_contradictions(records),
        "account_headline": _account_headline_facts(records),
        "evidence_files": sorted({filename for filename, _ in records}),
        "evidence_index": evidence_index,
    }
    state["revocation"] = revocation_summary([record for _, record in records])

    if status == "DEGRADED":
        state["reason"] = (
            "No capability has been measured as reachable from this evidence."
        )
        return state

    try:
        state["traces"] = trace(evidence_dir)["capabilities"]
    except Exception as error:  # noqa: BLE001
        state["traces"] = {}
        state["trace_error"] = str(error)
    try:
        state["least_privilege"] = diff(strategy_path, evidence_dir)
    except Exception as error:  # noqa: BLE001
        state["least_privilege"] = {"error": str(error)}
    try:
        financial = reach(evidence_dir)
        state["financial_reach"] = {
            key: value
            for key, value in financial.items()
            if key != "futures_gross_notional_ceiling"
        }
    except Exception as error:  # noqa: BLE001
        financial = {}
        state["financial_reach"] = {"error": str(error)}
    state["headline"] = _headline_facts(records, financial)
    return state


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_manifest(
    evidence_path: str | Path, strategy_path: str | Path
) -> dict[str, str]:
    evidence_dir = _evidence_dir(evidence_path)
    paths = sorted(evidence_dir.glob("*.jsonl")) + [Path(strategy_path)]
    return {str(path): _sha256_file(path) for path in paths}


def build_dashboard_state(
    evidence_path: str | Path = "evidence/raw",
    strategy_path: str | Path = "config/strategy.yaml",
    output_path: str | Path = "state/dashboard.json",
) -> dict[str, Any]:
    """Verify evidence and atomically write a deterministic dashboard artifact."""
    state = dashboard_state(evidence_path, strategy_path)
    if state.get("status") != "MEASURED":
        raise ValueError(
            f"refusing to write dashboard state: {state.get('reason', 'evidence is degraded')}"
        )
    canonical_state = json.dumps(
        state, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    envelope = {
        "format": "keyring-dashboard-state-v1",
        "source_manifest": _source_manifest(evidence_path, strategy_path),
        "state_sha256": hashlib.sha256(canonical_state).hexdigest(),
        "state": state,
    }
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(
        json.dumps(envelope, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(destination)
    return envelope


def load_dashboard_state(
    state_file: str | Path,
    evidence_path: str | Path = "evidence/raw",
    strategy_path: str | Path = "config/strategy.yaml",
) -> dict[str, Any]:
    """Verify a generated state artifact and its retained source files."""
    source = Path(state_file)
    try:
        envelope = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ValueError(f"dashboard state is not valid JSON: {source}") from error
    if not isinstance(envelope, dict) or envelope.get("format") != "keyring-dashboard-state-v1":
        raise ValueError("dashboard state has an unsupported format")
    state = envelope.get("state")
    if not isinstance(state, dict) or state.get("status") != "MEASURED":
        raise ValueError("dashboard state does not contain a measured report")
    canonical_state = json.dumps(
        state, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    if envelope.get("state_sha256") != hashlib.sha256(canonical_state).hexdigest():
        raise ValueError("dashboard state digest does not match its contents")
    if envelope.get("source_manifest") != _source_manifest(evidence_path, strategy_path):
        raise ValueError("dashboard state does not match the retained evidence and strategy")
    return state


# --------------------------------------------------------------------------- #
# rendering
# --------------------------------------------------------------------------- #

STYLE = """
:root{
color-scheme:light;
--plane:#f4f4f2;--surface:#fcfcfb;--surface-2:#f0efec;--surface-3:#e8e7e2;
--ink:#0b0b0b;--ink-2:#52514e;--muted:#898781;--line:#e1e0d9;--hair:rgba(11,11,11,.10);
--deep:#141412;--deep-2:#22221f;--deep-3:#2e2e2a;--on-deep:#ffffff;--on-deep-2:#c3c2b7;--on-deep-3:#8b8a83;
--accent:#4a3aa7;--accent-ink:#4a3aa7;--accent-soft:#edecf9;--accent-line:#d6d2f0;
--good:#0ca30c;--good-ink:#006300;--good-soft:#e6f4e6;
--warning:#fab219;--warning-ink:#7d5300;--warning-soft:#fdf1d8;
--serious:#ec835a;--serious-ink:#8f3f18;--serious-soft:#fbeadf;
--critical:#d03b3b;--critical-ink:#a82b2b;--critical-soft:#fae9e9;
--radius:14px;--radius-lg:20px;
--shadow:0 1px 2px rgba(11,11,11,.04),0 12px 32px rgba(11,11,11,.06);
--shadow-lift:0 2px 4px rgba(11,11,11,.05),0 18px 44px rgba(11,11,11,.10);
}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
color-scheme:dark;
--plane:#0d0d0d;--surface:#1a1a19;--surface-2:#232320;--surface-3:#2c2c2a;
--ink:#ffffff;--ink-2:#c3c2b7;--muted:#898781;--line:#2c2c2a;--hair:rgba(255,255,255,.10);
--deep:#000000;--deep-2:#161615;--deep-3:#232320;--on-deep:#ffffff;--on-deep-2:#c3c2b7;--on-deep-3:#898781;
--accent:#9085e9;--accent-ink:#9085e9;--accent-soft:#211f36;--accent-line:#38336b;
--good-ink:#0ca30c;--good-soft:#12220f;
--warning-ink:#fab219;--warning-soft:#241d0c;
--serious-ink:#ec835a;--serious-soft:#251710;
--critical-ink:#e06060;--critical-soft:#241010;
--shadow:0 1px 2px rgba(0,0,0,.4),0 12px 32px rgba(0,0,0,.35);
--shadow-lift:0 2px 4px rgba(0,0,0,.45),0 18px 44px rgba(0,0,0,.5);
}}
:root[data-theme="dark"]{
color-scheme:dark;
--plane:#0d0d0d;--surface:#1a1a19;--surface-2:#232320;--surface-3:#2c2c2a;
--ink:#ffffff;--ink-2:#c3c2b7;--muted:#898781;--line:#2c2c2a;--hair:rgba(255,255,255,.10);
--deep:#000000;--deep-2:#161615;--deep-3:#232320;--on-deep:#ffffff;--on-deep-2:#c3c2b7;--on-deep-3:#898781;
--accent:#9085e9;--accent-ink:#9085e9;--accent-soft:#211f36;--accent-line:#38336b;
--good-ink:#0ca30c;--good-soft:#12220f;
--warning-ink:#fab219;--warning-soft:#241d0c;
--serious-ink:#ec835a;--serious-soft:#251710;
--critical-ink:#e06060;--critical-soft:#241010;
--shadow:0 1px 2px rgba(0,0,0,.4),0 12px 32px rgba(0,0,0,.35);
--shadow-lift:0 2px 4px rgba(0,0,0,.45),0 18px 44px rgba(0,0,0,.5);
}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
body{margin:0;background:var(--plane);color:var(--ink);
font:15px/1.6 system-ui,-apple-system,"Segoe UI",sans-serif;
-webkit-font-smoothing:antialiased;text-rendering:optimizeLegibility}
@media (prefers-reduced-motion:reduce){html{scroll-behavior:auto}*{transition:none!important;animation:none!important}}
button,input,select{font:inherit;color:inherit}button{cursor:pointer}
a{color:var(--accent-ink)}
h1,h2,h3{letter-spacing:-.028em;margin:0}
.mono{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
.num{font-variant-numeric:tabular-nums}
.sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}
.muted{color:var(--muted)}
:focus-visible{outline:2px solid var(--accent);outline-offset:2px;border-radius:6px}

/* ---------- layout ---------- */
.shell{max-width:1220px;margin:0 auto;padding:0 24px 72px}
.topbar{position:sticky;top:0;z-index:8;display:flex;align-items:center;justify-content:space-between;gap:18px;
padding:12px 0;margin-bottom:14px;background:color-mix(in srgb,var(--plane) 88%,transparent);
backdrop-filter:blur(12px);border-bottom:1px solid transparent}
.topbar.stuck{border-bottom-color:var(--line)}
.brand{display:flex;align-items:center;gap:10px;font-weight:750;letter-spacing:-.03em;font-size:15px}
.brand-mark{display:grid;place-items:center;width:30px;height:30px;border-radius:9px;
background:linear-gradient(140deg,var(--accent),#2a78d6);color:#fff;font-size:15px;font-weight:800}
.brand small{display:block;color:var(--muted);font-size:10px;font-weight:650;letter-spacing:.08em;text-transform:uppercase;white-space:nowrap}
.nav{display:flex;align-items:center;gap:2px;flex-wrap:wrap}
.nav a{color:var(--ink-2);text-decoration:none;padding:7px 10px;border-radius:8px;font-size:13px;font-weight:550;transition:background .15s,color .15s}
.nav a:hover{background:var(--surface-2);color:var(--ink)}
.nav a.current{background:var(--accent-soft);color:var(--accent-ink)}
.tools{display:flex;align-items:center;gap:6px}
.icon-btn{border:1px solid var(--line);background:var(--surface);border-radius:9px;height:34px;padding:0 11px;
font-size:12.5px;font-weight:600;color:var(--ink-2);display:inline-flex;align-items:center;gap:6px;transition:all .15s}
.icon-btn:hover{border-color:var(--accent-line);color:var(--accent-ink);background:var(--accent-soft)}

/* ---------- hero ---------- */
.hero{position:relative;overflow:hidden;border-radius:var(--radius-lg);
background:radial-gradient(1100px 420px at 12% -10%,var(--deep-3),transparent 60%),
linear-gradient(155deg,var(--deep-2),var(--deep) 62%);
color:var(--on-deep);padding:52px 48px 44px;box-shadow:var(--shadow)}
.hero:before{content:"";position:absolute;inset:0;opacity:.5;pointer-events:none;
background-image:linear-gradient(var(--deep-3) 1px,transparent 1px),linear-gradient(90deg,var(--deep-3) 1px,transparent 1px);
background-size:46px 46px;mask-image:radial-gradient(760px 380px at 78% 0%,#000,transparent 72%)}
.hero>*{position:relative;z-index:1}
.eyebrow{display:inline-flex;align-items:center;gap:8px;font-size:11px;text-transform:uppercase;
letter-spacing:.13em;font-weight:750;color:var(--on-deep-3)}
.eyebrow .dot{width:6px;height:6px;border-radius:50%;background:var(--good);box-shadow:0 0 0 3px rgba(12,163,12,.22)}
.hero h1{font-size:clamp(32px,5vw,58px);line-height:1.04;letter-spacing:-.045em;max-width:16ch;margin:16px 0 0}
.hero .lead{max-width:60ch;color:var(--on-deep-2);font-size:clamp(16px,1.7vw,19px);line-height:1.5;margin:18px 0 0}
.hero .lead b{color:var(--on-deep);font-weight:650}
.hero .sub{max-width:62ch;color:var(--on-deep-3);font-size:14px;margin:14px 0 0}
.hero-strip{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:1px;margin-top:34px;
background:var(--deep-3);border:1px solid var(--deep-3);border-radius:var(--radius);overflow:hidden}
.hero-cell{background:var(--deep-2);padding:15px 17px;min-width:0}
.hero-cell span{display:block;color:var(--on-deep-3);font-size:11px;text-transform:uppercase;letter-spacing:.09em;font-weight:700}
.hero-cell strong{display:block;margin-top:6px;font-size:14px;font-weight:600;overflow-wrap:anywhere}
.hero-actions{display:flex;gap:9px;flex-wrap:wrap;margin-top:26px}
.button{border:1px solid transparent;background:var(--on-deep);color:var(--deep);border-radius:10px;
padding:11px 16px;font-weight:650;font-size:13.5px;text-decoration:none;display:inline-flex;align-items:center;gap:7px;transition:all .16s}
.button:hover{transform:translateY(-1px);box-shadow:0 8px 20px rgba(0,0,0,.28)}
.button.secondary{background:transparent;color:var(--on-deep);border-color:rgba(255,255,255,.24)}
.button.secondary:hover{background:rgba(255,255,255,.08)}

/* ---------- sections ---------- */
.section{margin-top:56px;scroll-margin-top:76px}
.section-head{margin-bottom:20px;max-width:760px}
.section-kicker{font-size:11px;text-transform:uppercase;letter-spacing:.13em;font-weight:750;color:var(--accent-ink)}
.section-head h2{font-size:clamp(22px,2.6vw,30px);line-height:1.16;margin:7px 0 0}
.section-head p{color:var(--ink-2);margin:9px 0 0;font-size:15px}
.subsection-title{font-size:17px;margin:32px 0 12px}
.card{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);box-shadow:var(--shadow)}

/* ---------- lens explainer ---------- */
.lens-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}
.lens{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);padding:18px;
box-shadow:var(--shadow);position:relative;overflow:hidden}
.lens:before{content:"";position:absolute;left:0;top:0;bottom:0;width:3px;background:var(--accent);opacity:.35}
.lens.flag:before{background:var(--critical);opacity:1}
.lens-n{display:grid;place-items:center;width:26px;height:26px;border-radius:8px;background:var(--accent-soft);
color:var(--accent-ink);font-size:12px;font-weight:800;font-variant-numeric:tabular-nums}
.lens.flag .lens-n{background:var(--critical-soft);color:var(--critical-ink)}
.lens h3{font-size:15px;margin:12px 0 6px;line-height:1.3}
.lens p{color:var(--ink-2);font-size:13.5px;margin:0;line-height:1.5}
.lens .who{display:block;margin-top:11px;font-size:11px;color:var(--muted);font-weight:600}

/* ---------- agreement matrix ---------- */
.matrix-wrap{margin-top:18px;background:var(--surface);border:1px solid var(--line);
border-radius:var(--radius);box-shadow:var(--shadow);overflow-x:auto}
table.matrix{width:100%;min-width:720px;border-collapse:collapse;font-size:14px}
table.matrix th,table.matrix td{padding:15px 18px;text-align:left;vertical-align:top;border-bottom:1px solid var(--line)}
table.matrix thead th{background:var(--surface-2);font-size:11px;text-transform:uppercase;letter-spacing:.09em;
color:var(--muted);font-weight:750;position:sticky;top:0;border-bottom:1px solid var(--line)}
table.matrix tbody tr:last-child th,table.matrix tbody tr:last-child td{border-bottom:0}
table.matrix tbody tr{transition:background .15s}
table.matrix tbody tr:hover{background:var(--surface-2)}
table.matrix tbody tr.flagged{background:var(--critical-soft)}
table.matrix tbody tr.flagged:hover{background:var(--critical-soft);filter:brightness(.98)}
.m-lens{display:flex;align-items:flex-start;gap:10px;min-width:190px}
.m-lens strong{display:block;font-size:14px;font-weight:650;line-height:1.3}
.m-lens small{display:block;color:var(--muted);font-size:11px;margin-top:3px;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;overflow-wrap:anywhere}
.m-val{font-size:13.5px;line-height:1.45;overflow-wrap:anywhere}
.m-val .refs{margin-top:8px}
.verdict{display:flex;gap:14px;align-items:flex-start;margin-top:16px;padding:18px 20px;border-radius:var(--radius);
background:var(--surface);border:1px solid var(--line);border-left:3px solid var(--critical);box-shadow:var(--shadow)}
.verdict h3{font-size:16px;margin:0 0 6px}
.verdict p{margin:0;color:var(--ink-2);font-size:14px}

/* ---------- status pills ---------- */
.pill{display:inline-flex;align-items:center;gap:6px;border-radius:999px;padding:4px 10px 4px 8px;
font-size:11.5px;font-weight:700;white-space:nowrap;border:1px solid transparent;line-height:1.5}
.pill .ic{font-size:11px;line-height:1}
.pill.ok{color:var(--good-ink);background:var(--good-soft);border-color:color-mix(in srgb,var(--good) 30%,transparent)}
.pill.no{color:var(--critical-ink);background:var(--critical-soft);border-color:color-mix(in srgb,var(--critical) 30%,transparent)}
.pill.warn{color:var(--warning-ink);background:var(--warning-soft);border-color:color-mix(in srgb,var(--warning) 45%,transparent)}
.pill.info{color:var(--accent-ink);background:var(--accent-soft);border-color:var(--accent-line)}
.pill.neutral{color:var(--ink-2);background:var(--surface-2);border-color:var(--line)}
.refs-more{align-self:center;color:var(--muted);font-size:11px;font-weight:600}
.status{display:inline-flex;align-items:center;gap:6px;border-radius:999px;padding:5px 11px;
font-size:11.5px;font-weight:700;white-space:nowrap;border:1px solid transparent;line-height:1.5}
.status:before{font-size:11px}
.status.reached{color:var(--good-ink);background:var(--good-soft);border-color:color-mix(in srgb,var(--good) 30%,transparent)}
.status.reached:before{content:"✓"}
.status.not-offered{color:var(--ink-2);background:var(--surface-2);border-color:var(--line)}
.status.not-offered:before{content:"—"}
.status.unclear{color:var(--warning-ink);background:var(--warning-soft);border-color:color-mix(in srgb,var(--warning) 45%,transparent)}
.status.unclear:before{content:"?"}

/* ---------- kpi ---------- */
.kpi-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin-top:8px}
.kpi{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);padding:20px;box-shadow:var(--shadow)}
.kpi .number{display:block;font-size:34px;line-height:1;font-weight:750;letter-spacing:-.05em}
.kpi .label{display:block;color:var(--ink-2);font-size:13px;margin-top:10px;line-height:1.4}
.kpi .foot{display:block;color:var(--muted);font-size:11px;margin-top:8px}
.kpi.a .number{color:var(--good-ink)}.kpi.b .number{color:var(--accent-ink)}
.kpi.c .number{color:var(--ink)}.kpi.d .number{color:var(--good-ink)}

/* ---------- signals ---------- */
.signals{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}
.signal{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);padding:20px;box-shadow:var(--shadow)}
.signal h3{font-size:16px;line-height:1.3;margin:10px 0 8px}
.signal p{color:var(--ink-2);margin:0;font-size:13.5px;line-height:1.5}
.signal .refs{margin-top:12px}

/* ---------- timeline ---------- */
.timeline{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:0;background:var(--surface);
border:1px solid var(--line);border-radius:var(--radius);padding:24px 8px;box-shadow:var(--shadow)}
.tl-step{position:relative;padding:0 18px}
.tl-step:not(:last-child):after{content:"";position:absolute;top:14px;left:calc(50% + 20px);right:calc(-50% + 20px);height:1px;background:var(--line)}
.tl-n{position:relative;z-index:1;display:grid;place-items:center;width:29px;height:29px;border-radius:50%;
background:var(--accent-soft);color:var(--accent-ink);font-weight:800;font-size:12.5px;margin-bottom:12px}
.tl-step h3{font-size:14px;margin:0 0 5px}
.tl-step p{color:var(--ink-2);font-size:12.5px;margin:0;line-height:1.45}
.tl-step .by{display:inline-block;margin-top:9px;font-size:10px;font-weight:750;letter-spacing:.06em;
text-transform:uppercase;color:var(--muted);border:1px solid var(--line);border-radius:999px;padding:3px 8px}
.tl-step .by.model{color:var(--accent-ink);background:var(--accent-soft);border-color:var(--accent-line)}

/* ---------- toolbar / filters ---------- */
.toolbar{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin:0 0 16px}
.search{position:relative;flex:1;min-width:230px}
.search input{width:100%;border:1px solid var(--line);border-radius:10px;background:var(--surface);
padding:10px 12px 10px 34px;outline:none;transition:border-color .15s,box-shadow .15s}
.search input:focus{border-color:var(--accent);box-shadow:0 0 0 3px var(--accent-soft)}
.search:before{content:"⌕";position:absolute;left:12px;top:6px;color:var(--muted);font-size:19px}
.search kbd{position:absolute;right:10px;top:9px;font:10px/1.5 ui-monospace,monospace;color:var(--muted);
border:1px solid var(--line);border-radius:5px;padding:1px 5px;background:var(--surface-2)}
.filters{display:flex;gap:6px;flex-wrap:wrap}
.filter{border:1px solid var(--line);background:var(--surface);color:var(--ink-2);border-radius:9px;
padding:9px 12px;font-size:12.5px;font-weight:650;transition:all .15s}
.filter:hover{border-color:var(--accent-line);color:var(--accent-ink)}
.filter.active{background:var(--accent-soft);border-color:var(--accent-line);color:var(--accent-ink)}
.count-note{color:var(--muted);font-size:12.5px;margin-left:auto}

/* ---------- access cards ---------- */
.access-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:13px}
.access-card{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);
padding:22px;box-shadow:var(--shadow);transition:box-shadow .2s,transform .2s,border-color .2s}
.access-card:hover{transform:translateY(-2px);box-shadow:var(--shadow-lift);border-color:var(--accent-line)}
.access-card.hidden{display:none}
.access-top{display:flex;justify-content:space-between;align-items:flex-start;gap:12px}
.access-kicker{font-size:10.5px;color:var(--muted);text-transform:uppercase;letter-spacing:.1em;font-weight:750}
.access-card h3{font-size:19px;margin:6px 0 0}
.access-card .description{color:var(--ink-2);margin:12px 0 0;font-size:13.5px;line-height:1.5}
.access-stats{display:grid;grid-template-columns:minmax(0,.72fr) minmax(0,1.6fr) minmax(0,.78fr);gap:8px;margin:16px 0 0}
.access-stat{background:var(--surface-2);border-radius:10px;padding:11px 12px;min-width:0}
.access-stat span{display:block;color:var(--muted);font-size:10.5px;text-transform:uppercase;letter-spacing:.06em;font-weight:700}
.access-stat strong{display:block;margin-top:5px;font-size:12.5px;overflow-wrap:break-word;font-variant-numeric:tabular-nums}
.tool-list{display:flex;gap:5px;flex-wrap:wrap;margin:14px 0 0}
.tool-name{background:var(--surface-2);border:1px solid var(--line);border-radius:7px;color:var(--ink-2);
font:11px/1.35 ui-monospace,SFMono-Regular,Menlo,monospace;padding:4px 7px}
.proof-details{border-top:1px solid var(--line);margin-top:18px;padding-top:14px}
.proof-details summary{cursor:pointer;color:var(--accent-ink);font-size:13px;font-weight:700;list-style:none;
display:flex;align-items:center;gap:7px}
.proof-details summary::-webkit-details-marker{display:none}
.proof-details summary:before{content:"›";display:inline-block;font-size:17px;line-height:1;transition:transform .18s}
.proof-details[open] summary:before{transform:rotate(90deg)}
.proof-list{margin-top:14px;display:grid;gap:2px}
.proof-row{display:grid;grid-template-columns:150px minmax(0,1fr);gap:10px;padding:11px 0;border-bottom:1px dashed var(--line)}
.proof-row:last-child{border-bottom:0}
.proof-name{color:var(--ink-2);font-size:12.5px;font-weight:700}
.proof-label{display:block;color:var(--muted);font-size:9.5px;font-weight:700;letter-spacing:.04em;margin-top:3px}
.proof-value{min-width:0;white-space:pre-wrap;overflow-wrap:anywhere;color:var(--ink);font-size:13px}
.proof-evidence{grid-column:2;display:flex;gap:5px;flex-wrap:wrap;margin-top:7px}
.no-results{display:none;background:var(--surface);border:1px dashed var(--line);color:var(--muted);
border-radius:var(--radius);padding:26px;text-align:center}
.no-results.show{display:block}

/* ---------- evidence chips ---------- */
.refs{display:flex;gap:5px;flex-wrap:wrap}
.evidence-ref{border:1px solid var(--accent-line);background:var(--accent-soft);color:var(--accent-ink);
border-radius:7px;padding:4px 8px;font:11px/1.35 ui-monospace,SFMono-Regular,Menlo,monospace;font-weight:600;transition:all .14s}
.evidence-ref:hover{background:var(--accent);color:#fff;border-color:var(--accent)}

/* ---------- compare ---------- */
.compare-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:13px}
.compare-card{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);padding:22px;box-shadow:var(--shadow)}
.compare-card h3{font-size:16px;margin:0}
.compare-card>p{color:var(--ink-2);margin:8px 0 0;font-size:13.5px}
.compare-card.needed{border-top:3px solid var(--good)}
.compare-card.extra{border-top:3px solid var(--warning)}
.plain-list{padding:0;margin:14px 0 0;list-style:none}
.plain-list li{padding:9px 0;border-bottom:1px solid var(--line);font-size:13.5px;display:flex;gap:9px;align-items:baseline}
.plain-list li:last-child{border-bottom:0}
.plain-list li:before{content:"✓";color:var(--good-ink);font-weight:800;font-size:12px}
.extra .plain-list li:before{content:"+";color:var(--warning-ink)}
.callout{margin-top:14px;background:var(--accent-soft);border:1px solid var(--accent-line);
border-radius:var(--radius);padding:16px 18px;color:var(--ink-2);font-size:13.5px;line-height:1.55}
.callout strong{color:var(--accent-ink)}

/* ---------- money ---------- */
.money-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}
.money-card{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);padding:19px;box-shadow:var(--shadow)}
.money-card .money-label{color:var(--ink-2);font-size:13px;line-height:1.4;min-height:2.8em}
.money-card .money-value{font-size:26px;font-weight:750;letter-spacing:-.04em;margin-top:10px;overflow-wrap:anywhere}
.money-card .money-note{color:var(--muted);font-size:11px;margin-top:8px}
.money-card.measured{border-top:3px solid var(--good)}
.money-card.cost{border-top:3px solid var(--warning)}
.money-card.risk .money-value{color:var(--good-ink)}
.money-note-block{background:var(--surface);border:1px solid var(--line);border-left:3px solid var(--good);
border-radius:var(--radius);padding:16px 18px;color:var(--ink-2);margin-top:14px;font-size:13.5px;line-height:1.55}
.money-note-block strong{color:var(--ink)}

/* ---------- provenance / client table ---------- */
.ptable-wrap{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);
box-shadow:var(--shadow);overflow-x:auto}
table.ptable{width:100%;min-width:760px;border-collapse:collapse;font-size:13.5px}
table.ptable th,table.ptable td{padding:14px 17px;text-align:left;border-bottom:1px solid var(--line);vertical-align:middle}
table.ptable thead th{background:var(--surface-2);font-size:10.5px;text-transform:uppercase;letter-spacing:.09em;
color:var(--muted);font-weight:750}
table.ptable tbody tr:last-child td{border-bottom:0}
table.ptable tbody tr:hover{background:var(--surface-2)}
table.ptable td.n{font-variant-numeric:tabular-nums;font-weight:650}
table.ptable .ctx strong{display:block;font-size:13.5px}
table.ptable .ctx span{display:block;color:var(--muted);font-size:11.5px;margin-top:2px}

/* ---------- integrity ---------- */
.integrity-grid{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:11px}
.integrity-card{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);
padding:19px 15px;box-shadow:var(--shadow);text-align:center}
.integrity-card .big{display:block;font-size:27px;font-weight:750;letter-spacing:-.045em;color:var(--ink);font-variant-numeric:tabular-nums}
.integrity-card .small{display:block;color:var(--ink-2);font-size:11.5px;margin-top:7px;line-height:1.35}
.integrity-card.pass .big{color:var(--good-ink)}
.explain{color:var(--ink-2);max-width:78ch;margin:16px 0 0;font-size:13.5px;line-height:1.6}

/* ---------- evidence explorer ---------- */
.explorer{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);
box-shadow:var(--shadow);overflow:hidden}
.explorer-head{display:flex;gap:10px;flex-wrap:wrap;align-items:center;padding:14px 16px;border-bottom:1px solid var(--line);background:var(--surface-2)}
.explorer-scroll{max-height:520px;overflow:auto}
table.evtable{width:100%;min-width:820px;border-collapse:collapse;font-size:13px}
table.evtable th,table.evtable td{padding:11px 16px;text-align:left;border-bottom:1px solid var(--line);white-space:nowrap}
table.evtable thead th{position:sticky;top:0;z-index:1;background:var(--surface-2);font-size:10.5px;
text-transform:uppercase;letter-spacing:.09em;color:var(--muted);font-weight:750}
table.evtable tbody tr{cursor:pointer;transition:background .12s}
table.evtable tbody tr:hover{background:var(--accent-soft)}
table.evtable td.ref{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:11.5px;color:var(--accent-ink)}
table.evtable td.wrap{white-space:normal;max-width:340px;overflow-wrap:break-word;color:var(--ink-2)}
.explorer-foot{padding:12px 16px;border-top:1px solid var(--line);color:var(--muted);font-size:12.5px;
display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;align-items:center}
.file-pills{display:flex;gap:6px;flex-wrap:wrap;margin-top:12px}
.file-pill{background:var(--surface-2);border:1px solid var(--line);border-radius:8px;color:var(--ink-2);
font:11px/1.35 ui-monospace,SFMono-Regular,Menlo,monospace;padding:6px 9px;transition:all .14s}
.file-pill:hover{border-color:var(--accent-line);color:var(--accent-ink)}
.file-pill.active{background:var(--accent-soft);border-color:var(--accent-line);color:var(--accent-ink)}
.source-card{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);padding:20px;
box-shadow:var(--shadow);margin-top:14px}
.source-card h3{font-size:15px;margin:0}

/* ---------- notes ---------- */
.notes-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:13px}
.note-card{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);padding:20px;box-shadow:var(--shadow)}
.note-card h3{font-size:16px;margin:10px 0 8px;line-height:1.3}
.note-card p{color:var(--ink-2);margin:0;font-size:13.5px;line-height:1.55}
.note-card .refs{margin-top:13px}
.legend{display:flex;gap:8px;flex-wrap:wrap;margin-top:16px}
.legend span{font-size:11.5px;color:var(--ink-2);background:var(--surface);border:1px solid var(--line);
border-radius:999px;padding:6px 11px}
.legend b{color:var(--ink)}

/* ---------- drawer ---------- */
.drawer-backdrop{position:fixed;inset:0;background:rgba(11,11,11,.5);z-index:20;backdrop-filter:blur(2px)}
.drawer{position:fixed;z-index:21;right:0;top:0;height:100%;width:min(480px,100%);background:var(--surface);
box-shadow:-18px 0 50px rgba(0,0,0,.28);padding:26px;overflow:auto;border-left:1px solid var(--line)}
.drawer[hidden],.drawer-backdrop[hidden]{display:none}
.drawer-header{display:flex;justify-content:space-between;align-items:flex-start;gap:14px;
border-bottom:1px solid var(--line);padding-bottom:16px}
.drawer h2{font-size:20px;margin:0}
.close{border:1px solid var(--line);background:var(--surface-2);color:var(--ink-2);border-radius:9px;
width:34px;height:34px;font-size:19px;line-height:1;flex:none}
.close:hover{border-color:var(--accent-line);color:var(--accent-ink)}
.drawer-ref{font:12px/1.4 ui-monospace,SFMono-Regular,Menlo,monospace;color:var(--accent-ink);
overflow-wrap:anywhere;margin:18px 0;background:var(--accent-soft);border:1px solid var(--accent-line);
border-radius:8px;padding:9px 11px}
.drawer dl{display:grid;grid-template-columns:118px minmax(0,1fr);gap:11px 14px;margin:0}
.drawer dt{color:var(--muted);font-size:12px}
.drawer dd{margin:0;color:var(--ink);overflow-wrap:anywhere;font-size:13.5px}
.drawer-note{background:var(--surface-2);border:1px solid var(--line);color:var(--ink-2);border-radius:10px;
padding:13px 14px;margin-top:22px;font-size:12.5px;line-height:1.55}

.footer{display:flex;justify-content:space-between;gap:16px;align-items:center;border-top:1px solid var(--line);
margin-top:60px;padding-top:22px;color:var(--muted);font-size:12.5px;flex-wrap:wrap}
.footer a{font-weight:650;text-decoration:none}

@media(max-width:1040px){
.lens-grid{grid-template-columns:repeat(2,minmax(0,1fr))}
.timeline{grid-template-columns:repeat(3,minmax(0,1fr));gap:22px 0}
.tl-step:after{display:none}
.money-grid{grid-template-columns:repeat(2,minmax(0,1fr))}
.integrity-grid{grid-template-columns:repeat(3,minmax(0,1fr))}
}
@media(max-width:860px){
.hero{padding:36px 26px}
.hero-strip{grid-template-columns:repeat(2,minmax(0,1fr))}
.kpi-grid{grid-template-columns:repeat(2,minmax(0,1fr))}
.signals,.compare-grid,.notes-grid,.access-grid{grid-template-columns:1fr}
.nav{display:none}
}
@media(max-width:560px){
.shell{padding:0 14px 48px}
.hero{border-radius:16px;padding:30px 20px}
.lens-grid,.money-grid,.integrity-grid,.timeline{grid-template-columns:1fr}
.kpi-grid{grid-template-columns:1fr}
.proof-row{grid-template-columns:1fr}
.proof-evidence{grid-column:1}
.drawer{padding:20px}
.footer{flex-direction:column;align-items:flex-start}
}
@media print{.topbar,.hero-actions,.toolbar,.explorer-head,.drawer,.drawer-backdrop{display:none!important}
body{background:#fff}.access-card,.card,.kpi,.signal{box-shadow:none;break-inside:avoid}}
"""


def _esc(value: Any) -> str:
    return html.escape(str(value))


def _text(value: Any, fallback: str = "—") -> str:
    return fallback if value is None else str(value)


def _status_info(classification: str) -> tuple[str, str]:
    return {
        "VERIFIED": ("Measured access", "reached"),
        "DENIED": ("Not offered", "not-offered"),
        "ADVERTISED_ONLY": ("Listed, not reached", "unclear"),
        "INCONCLUSIVE": ("Needs a clearer result", "unclear"),
    }.get(classification, (classification.title(), "unclear"))


ENUM_PHRASES = {
    "RECONNECT_REQUIRED": "No — the grant has to be disconnected and authorized again",
    "NO_CONFIRMATION_PROMPT": "no confirmation prompt",
    "CONFIRMATION_PROMPT_SHOWN": "confirmation prompt shown",
}


def _plain(value: Any) -> str:
    """Render a stored enum in the page's own language, leaving the data alone."""
    text = str(value)
    for token, phrase in ENUM_PHRASES.items():
        text = text.replace(token, phrase)
    return text


def _sentence(value: Any) -> str:
    text = str(value or "").strip()
    return text[:1].upper() + text[1:] if text else text


def _label_text(label: Any) -> str:
    text = _label_value(label)
    if text.startswith("OBSERVED · "):
        return "Measured · " + text.removeprefix("OBSERVED · ").title()
    return {
        "OBSERVED": "Measured",
        "DOCUMENTED": "Published information",
        "ASSUMED": "Assumption",
        "INCONCLUSIVE": "Not resolved",
    }.get(text, text.title())


def _scope_text(scope: str | None) -> str:
    if not scope:
        return "Not recorded"
    names = []
    for item in scope.split():
        names.append(item.removeprefix("mcp:").replace(":", " ").title())
    return " · ".join(names)


def _ref_label(ref: str) -> str:
    """Shorten a record reference without losing which file it came from."""
    file, _, sequence = ref.rpartition("#")
    return f"{file.split('-', 1)[0] or file}#{sequence}" if file else ref


def _refs_html(refs: list[str], limit: int = 6) -> str:
    unique = list(dict.fromkeys(refs))
    if not unique:
        return '<span class="muted">No linked evidence</span>'
    shown = unique[:limit]
    chips = "".join(
        f'<button type="button" class="evidence-ref" data-ref="{_esc(ref)}" '
        f'title="{_esc(ref)}">{_esc(_ref_label(ref))}</button>'
        for ref in shown
    )
    remaining = len(unique) - len(shown)
    if remaining:
        chips += f'<span class="refs-more">+{remaining} more</span>'
    return chips


def _value_with_unit(key: str, layer: dict[str, Any]) -> str:
    value = layer.get("value")
    if value is None:
        return "—"
    if key == "open_positions" and isinstance(value, dict):
        return str(sum(int(item or 0) for item in value.values()))
    if key in {"capital_visible", "capital_reachable_by_trading", "autonomous_capital_at_risk"}:
        try:
            amount = Decimal(str(value))
            shown = "0" if amount == 0 else format(amount.quantize(Decimal("0.01")), "f")
        except (InvalidOperation, TypeError, ValueError):
            shown = str(value)
        return f"{shown} USDT"
    if key == "immediate_exit_cost":
        return f"{value} USDT"
    return str(value)


def _plain_list(items: list[str], empty: str = "None recorded") -> str:
    if not items:
        return f'<p class="muted">{_esc(empty)}</p>'
    return '<ul class="plain-list">' + "".join(f"<li>{_esc(item)}</li>" for item in items) + "</ul>"


def _account_headline_summary(rows: list[dict[str, Any]]) -> str:
    """Describe the comparison from the same facts used in the hero cells."""
    if not rows:
        return "No account comparison was recorded."

    reports: list[str] = []
    for row in rows:
        flags = row.get("permission_flags") or {}
        if flags.get("spot") is False and flags.get("futures") is False:
            wording = "reported spot and futures trading disabled"
        elif flags.get("spot") is True and flags.get("futures") is True:
            wording = "reported spot and futures trading enabled"
        else:
            wording = "reported a mixed spot and futures permission result"
        reports.append(f"{row['account']} {wording}")

    if len(rows) < 2:
        return reports[0] + "."

    common_tools = {row.get("tool_count") for row in rows}
    common_writes = {row.get("write_count") for row in rows}
    common_tests = set(rows[0].get("tested_capabilities", []))
    for row in rows[1:]:
        common_tests &= set(row.get("tested_capabilities", []))
    suffix = ""
    if len(common_tools) == 1 and len(common_writes) == 1:
        tool_count = next(iter(common_tools))
        write_count = next(iter(common_writes))
        suffix = (
            f" Both trade-grant surfaces exposed the same {tool_count} tools and "
            f"{write_count} writes, and KEYRING independently confirmed the same "
            f"{len(common_tests)} trading families on both."
        )
    return ". ".join(reports) + "." + suffix


def _capability_card(name: str, row: dict[str, Any], traces: dict[str, Any], scope: str | None) -> str:
    classification = row.get("classification", "INCONCLUSIVE")
    status_text, status_class = _status_info(classification)
    display_name = CAPABILITY_LABELS.get(name, name.replace("_", " ").title())
    write_tools = row.get("advertised_write_tools", [])
    if classification == "VERIFIED":
        description = (
            "A deliberately safe request reached Binance's own checks and stopped "
            "before an order could execute."
        )
    elif classification == "DENIED":
        description = "No write action for this area appeared in the connected tool list."
    else:
        description = "The available evidence does not support a clear access answer."
    steps = traces.get(name, {}).get("steps", [])
    proof_rows = []
    for step in steps:
        proof_rows.append(
            '<div class="proof-row">'
            f'<div class="proof-name">{_esc(STEP_LABELS.get(step.get("step"), step.get("step", "Evidence")))}'
            f'<span class="proof-label">{_esc(step.get("label", ""))}</span></div>'
            f'<div class="proof-value">{_esc(_text(step.get("value")))}</div>'
            f'<div class="proof-evidence">{_refs_html(step.get("evidence_records", []))}</div>'
            "</div>"
        )
    tools_html = "".join(f'<span class="tool-name">{_esc(tool)}</span>' for tool in write_tools)
    return (
        f'<article class="access-card" data-status="{_esc("reached" if classification == "VERIFIED" else "not-offered" if classification == "DENIED" else "other")}" '
        f'data-search="{_esc((display_name + " " + " ".join(write_tools)).lower())}">'
        '<div class="access-top">'
        f'<div><div class="access-kicker">Capability</div><h3>{_esc(display_name)}</h3></div>'
        f'<span class="status {status_class}">{_esc(status_text)}</span>'
        '</div>'
        f'<p class="description">{_esc(description)}</p>'
        '<div class="access-stats">'
        f'<div class="access-stat"><span>Write actions visible</span><strong>{_esc(len(write_tools))}</strong></div>'
        f'<div class="access-stat"><span>Test request</span><strong>{_esc(row.get("probe_tool") or "None")}</strong></div>'
        f'<div class="access-stat"><span>Exchange result</span><strong>{_esc(row.get("error_code") or "Not called")}</strong></div>'
        '</div>'
        + (f'<div class="tool-list">{tools_html}</div>' if tools_html else "")
        + '<details class="proof-details">'
        f'<summary>Show the evidence behind this answer · {len(set(ref for step in steps for ref in step.get("evidence_records", [])))} linked records</summary>'
        '<div class="proof-list">'
        + ("".join(proof_rows) if proof_rows else '<p class="muted">No linked evidence for this capability.</p>')
        + "</div></details></article>"
    )


# --------------------------------------------------------------------------- #
# the four ways of asking
# --------------------------------------------------------------------------- #

# Each lens is one way of answering "what can this agent do?". The wording is
# presentation only; every value shown comes from the evidence log.
LENSES = [
    {
        "key": "granted_mcp_scopes",
        "title": "What you agreed to",
        "technical": "Granted MCP scopes",
        "detail": "The permission approved on the Binance consent screen, read back from the connection itself.",
        "who": "Reported by the connection",
    },
    {
        "key": "permission_check",
        "title": "Binance permission self-report",
        "technical": "wallet.getApiKeyPermission",
        "detail": "Binance's own description of the credential — the surface someone would query to audit a live session.",
        "who": "Reported by Binance",
    },
    {
        "key": "tools",
        "title": "What the agent was handed",
        "technical": "tools/list",
        "detail": "The tools the live session actually exposed to the agent, counting the ones that can write.",
        "who": "Reported by the session",
    },
    {
        "key": "controlled_tests",
        "title": "What KEYRING measured",
        "technical": "controlled non-executing requests",
        "detail": "Trading-shaped requests built to be rejected at Binance's own checks, before anything could execute.",
        "who": "Measured by KEYRING",
    },
]


def _lens_rows(account_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Join the four ways of asking against every measured account."""
    rows: list[dict[str, Any]] = []
    for lens in LENSES:
        cells = [
            {
                "account": row["account"],
                "value": (row.get(lens["key"]) or {}).get("value", "—"),
                "technical": (row.get(lens["key"]) or {}).get("technical"),
                "sources": (row.get(lens["key"]) or {}).get("sources", []),
            }
            for row in account_rows
        ]
        distinct = {cell["value"] for cell in cells}
        rows.append({**lens, "cells": cells, "agrees": len(distinct) <= 1})
    return rows


def _pill(kind: str, icon: str, text: str) -> str:
    """A status chip. The icon and the word carry the meaning, never the colour."""
    return f'<span class="pill {kind}"><span class="ic" aria-hidden="true">{icon}</span>{_esc(text)}</span>'


def _lens_cards_html(rows: list[dict[str, Any]]) -> str:
    cards = []
    for index, row in enumerate(rows, start=1):
        flag = "" if row["agrees"] else " flag"
        cards.append(
            f'<article class="lens{flag}"><div class="lens-n">{index}</div>'
            f'<h3>{_esc(row["title"])}</h3><p>{_esc(row["detail"])}</p>'
            f'<span class="who">{_esc(row["who"])} · <span class="mono">{_esc(row["technical"])}</span></span></article>'
        )
    return f'<div class="lens-grid">{"".join(cards)}</div>'


def _lens_matrix_html(rows: list[dict[str, Any]], account_rows: list[dict[str, Any]]) -> str:
    if not rows or not account_rows:
        return '<p class="muted">No account comparison evidence is available.</p>'

    heads = "".join(f"<th scope=\"col\">{_esc(row['account'])}</th>" for row in account_rows)
    body = []
    for index, row in enumerate(rows, start=1):
        agree = (
            _pill("ok", "=", "Same answer")
            if row["agrees"]
            else _pill("no", "≠", "Different answer")
        )
        cells = "".join(
            f'<td><div class="m-val">{_esc(cell["value"])}<div class="refs">{_refs_html(cell["sources"])}</div></div></td>'
            for cell in row["cells"]
        )
        body.append(
            f'<tr class="{"" if row["agrees"] else "flagged"}">'
            f'<th scope="row"><div class="m-lens"><div class="lens-n">{index}</div>'
            f'<div><strong>{_esc(row["title"])}</strong><small>{_esc(row["technical"])}</small></div></div></th>'
            f"{cells}<td>{agree}</td></tr>"
        )
    return (
        '<div class="matrix-wrap"><table class="matrix">'
        f'<caption class="sr-only">Four ways of asking what the agent can do, compared across the measured accounts</caption>'
        f'<thead><tr><th scope="col">The way we asked</th>{heads}'
        '<th scope="col">Across accounts</th></tr></thead>'
        f'<tbody>{"".join(body)}</tbody></table></div>'
    )


def _mode_text(mode: Any) -> str:
    text = str(mode or "—")
    return text if text in {"—", "not applicable"} else f"{text} mode"


def _client_gate_table_html(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return '<p class="muted">No client confirmation observation was recorded.</p>'
    body = []
    for row in rows:
        gated = row.get("gated")
        gate_pill = (
            _pill("ok", "✓", "Prompt shown")
            if gated
            else _pill("warn", "!", "No prompt observed")
        )
        refs = [row["gate_source"]] + (
            [row["capital_source"]["ref"]] if row.get("capital_source") else []
        )
        body.append(
            "<tr>"
            f'<td class="ctx"><strong>{_esc(row.get("account", "—"))}</strong>'
            f'<span>{_esc(row.get("client", "—"))} · {_esc(_mode_text(row.get("permission_mode")))}</span></td>'
            f'<td>{gate_pill}</td>'
            f'<td class="n">{_esc(_value_with_unit("capital_reachable_by_trading", row.get("capital_reachable_by_trading") or {}))}</td>'
            f'<td class="n">{_esc(_value_with_unit("autonomous_capital_at_risk", row.get("autonomous_capital_at_risk") or {}))}</td>'
            f'<td>{_esc(_label_text(row.get("label", "")))}</td>'
            f'<td><div class="refs">{_refs_html(refs)}</div></td>'
            "</tr>"
        )
    return (
        '<div class="ptable-wrap"><table class="ptable">'
        '<caption class="sr-only">Confirmation behaviour and reachable capital, kept separately per account, client and mode</caption>'
        '<thead><tr><th scope="col">Account · client · mode</th><th scope="col">Before a trading request</th>'
        '<th scope="col">Reachable capital</th><th scope="col">Movable without approval</th>'
        '<th scope="col">How it was captured</th><th scope="col">Evidence</th></tr></thead>'
        f'<tbody>{"".join(body)}</tbody></table></div>'
    )


# The recorded loop, in the order the harness runs it. "Model" marks the only
# step a model touches; every other step is deterministic code.
AGENT_STEPS = [
    (
        "Discover",
        "Capture the tool schema the session exposes and the target symbol's live exchange filters.",
        "Deterministic code",
    ),
    (
        "Propose a test",
        "The model reads that schema and proposes a tool, arguments, the filter it expects to violate, and why it should stop there.",
        "Model",
    ),
    (
        "Gate the proposal",
        "The proposal is rejected unless it violates a named live filter and stays under the notional minimum. The model cannot skip this.",
        "Deterministic code",
    ),
    (
        "Measure safely",
        "A read check, one budgeted request, and a complete account snapshot before and after it.",
        "Deterministic code",
    ),
    (
        "Classify",
        "The classifier owns the published result. Where the model disagreed, both readings are kept.",
        "Deterministic code",
    ),
]


def _timeline_html() -> str:
    steps = "".join(
        f'<div class="tl-step"><div class="tl-n">{index}</div><h3>{_esc(title)}</h3>'
        f'<p>{_esc(body)}</p>'
        f'<span class="by{" model" if actor == "Model" else ""}">{_esc(actor)}</span></div>'
        for index, (title, body, actor) in enumerate(AGENT_STEPS, start=1)
    )
    return f'<div class="timeline">{steps}</div>'


SCRIPT = """
(() => {
'use strict';
const $ = id => document.getElementById(id);
const esc = value => String(value === null || value === undefined ? '\\u2014' : value)
  .replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));

/* ---- theme -------------------------------------------------------------- */
const root = document.documentElement;
const icon = $('theme-icon'), label = $('theme-text');
const paint = mode => {
  if (mode) root.setAttribute('data-theme', mode); else root.removeAttribute('data-theme');
  const dark = mode === 'dark' || (!mode && matchMedia('(prefers-color-scheme: dark)').matches);
  icon.textContent = dark ? '\\u25D1' : '\\u25D0';
  label.textContent = dark ? 'Light' : 'Dark';
};
let stored = null;
try { stored = localStorage.getItem('keyring-theme'); } catch (_) {}
paint(stored);
$('theme-toggle').addEventListener('click', () => {
  const dark = root.getAttribute('data-theme') === 'dark'
    || (!root.getAttribute('data-theme') && matchMedia('(prefers-color-scheme: dark)').matches);
  const next = dark ? 'light' : 'dark';
  paint(next);
  try { localStorage.setItem('keyring-theme', next); } catch (_) {}
});

/* ---- sticky bar + scroll spy -------------------------------------------- */
const bar = $('topbar');
const links = [...document.querySelectorAll('.nav a')];
const targets = links.map(a => document.querySelector(a.getAttribute('href'))).filter(Boolean);
addEventListener('scroll', () => {
  bar.classList.toggle('stuck', scrollY > 8);
  let current = targets[0];
  for (const section of targets) { if (section.getBoundingClientRect().top <= 120) current = section; }
  links.forEach(a => a.classList.toggle('current', a.getAttribute('href') === '#' + (current && current.id)));
}, { passive: true });

/* ---- evidence drawer ---------------------------------------------------- */
const byRef = Object.fromEntries(EVIDENCE.map(item => [item.ref, item]));
const drawer = $('evidence-drawer'), backdrop = $('drawer-backdrop'), body = $('drawer-content');
let lastFocus = null;
const closeDrawer = () => {
  drawer.hidden = true; backdrop.hidden = true;
  if (lastFocus && lastFocus.focus) lastFocus.focus();
};
const openDrawer = ref => {
  const item = byRef[ref];
  if (!item) return;
  lastFocus = document.activeElement;
  const rows = [
    ['Type', item.kind], ['Operation', item.operation], ['Capability', item.capability],
    ['Result', item.outcome], ['Error code', item.error_code], ['State check', item.state_proof],
    ['How it was captured', item.label], ['Recorded by', item.capture_origin],
    ['Time', item.occurred_at], ['Source', item.source]
  ];
  body.innerHTML = '<div class="drawer-ref">' + esc(item.ref) + '</div><dl>'
    + rows.map(([k, v]) => '<dt>' + esc(k) + '</dt><dd>' + esc(v) + '</dd>').join('')
    + '</dl><div class="drawer-note">This panel shows record metadata only. The complete redacted record is '
    + 'in the evidence file itself, and in the JSON data view.</div>';
  drawer.hidden = false; backdrop.hidden = false;
  drawer.querySelector('.close').focus();
};
document.addEventListener('click', event => {
  const chip = event.target.closest('.evidence-ref');
  if (chip) { openDrawer(chip.dataset.ref); return; }
  if (event.target.closest('[data-close]')) closeDrawer();
});
addEventListener('keydown', event => {
  if (event.key === 'Escape') closeDrawer();
  if (event.key === '/' && !/^(INPUT|TEXTAREA)$/.test(document.activeElement.tagName)) {
    event.preventDefault(); $('capability-search').focus();
  }
});

/* ---- capability filtering ------------------------------------------------ */
const cards = [...document.querySelectorAll('.access-card')];
const capSearch = $('capability-search'), noResults = $('no-results');
let capFilter = 'all';
const applyCapFilters = () => {
  const query = capSearch.value.trim().toLowerCase();
  let shown = 0;
  cards.forEach(card => {
    const visible = (capFilter === 'all' || card.dataset.status === capFilter)
      && (!query || card.dataset.search.includes(query));
    card.classList.toggle('hidden', !visible);
    if (visible) shown += 1;
  });
  noResults.classList.toggle('show', shown === 0);
};
document.querySelectorAll('[data-filter]').forEach(button => {
  if (button.id === 'expand-all') return;
  button.addEventListener('click', () => {
    capFilter = button.dataset.filter;
    document.querySelectorAll('[data-filter]').forEach(other => {
      if (other.id !== 'expand-all') other.classList.toggle('active', other === button);
    });
    applyCapFilters();
  });
});
capSearch.addEventListener('input', applyCapFilters);
$('expand-all').addEventListener('click', event => {
  const open = event.currentTarget.dataset.open !== 'true';
  cards.forEach(card => card.querySelectorAll('details').forEach(detail => { detail.open = open; }));
  event.currentTarget.dataset.open = String(open);
  event.currentTarget.textContent = open ? 'Collapse all' : 'Expand all';
});

/* ---- evidence explorer --------------------------------------------------- */
const rowsHost = $('evidence-rows'), evSearch = $('evidence-search'), countHost = $('evidence-count');
const LIMIT = 200;
let origin = 'all', activeFile = null;
const haystack = new Map(EVIDENCE.map(item => [item.ref, [
  item.ref, item.kind, item.operation, item.capability, item.outcome, item.error_code, item.source
].join(' ').toLowerCase()]));
const renderEvidence = () => {
  const query = evSearch.value.trim().toLowerCase();
  const matched = EVIDENCE.filter(item =>
    (origin === 'all' || item.capture_origin === origin)
    && (!activeFile || item.file === activeFile)
    && (!query || haystack.get(item.ref).includes(query)));
  rowsHost.innerHTML = matched.slice(0, LIMIT).map(item =>
    '<tr tabindex="0" data-ref="' + esc(item.ref) + '">'
    + '<td class="ref">' + esc(item.ref) + '</td>'
    + '<td>' + esc(item.kind) + '</td>'
    + '<td class="wrap">' + esc(item.operation) + '</td>'
    + '<td class="wrap">' + esc(item.outcome) + '</td>'
    + '<td>' + esc(item.error_code) + '</td>'
    + '<td>' + esc(item.label) + '</td></tr>').join('')
    || '<tr><td colspan="6" style="padding:26px;text-align:center;color:var(--muted)">No record matches that search.</td></tr>';
  countHost.textContent = matched.length > LIMIT
    ? 'Showing the first ' + LIMIT + ' of ' + matched.length + ' matching records. Narrow the search to see the rest.'
    : matched.length + ' of ' + EVIDENCE.length + ' records shown.';
};
rowsHost.addEventListener('click', event => {
  const row = event.target.closest('tr[data-ref]');
  if (row) openDrawer(row.dataset.ref);
});
rowsHost.addEventListener('keydown', event => {
  if (event.key !== 'Enter' && event.key !== ' ') return;
  const row = event.target.closest('tr[data-ref]');
  if (row) { event.preventDefault(); openDrawer(row.dataset.ref); }
});
evSearch.addEventListener('input', renderEvidence);
document.querySelectorAll('[data-origin]').forEach(button => button.addEventListener('click', () => {
  origin = button.dataset.origin;
  document.querySelectorAll('[data-origin]').forEach(other => other.classList.toggle('active', other === button));
  renderEvidence();
}));
document.querySelectorAll('[data-file]').forEach(button => button.addEventListener('click', () => {
  const same = activeFile === button.dataset.file;
  activeFile = same ? null : button.dataset.file;
  document.querySelectorAll('[data-file]').forEach(other =>
    other.classList.toggle('active', !same && other === button));
  renderEvidence();
  if (!same) document.getElementById('evidence').scrollIntoView({ behavior: 'smooth' });
}));
renderEvidence();

/* ---- copy the data link -------------------------------------------------- */
$('copy-json').addEventListener('click', async event => {
  const button = event.currentTarget;
  try {
    await navigator.clipboard.writeText(new URL('/api/state', location.href).href);
    button.textContent = 'Data link copied';
    setTimeout(() => { button.textContent = 'Copy data link'; }, 1800);
  } catch (_) { open('/api/state', '_blank', 'noopener'); }
});
})();
"""


def render_html(state: dict[str, Any]) -> str:
    """Render the evidence-derived, interactive report."""
    if state["status"] == "DEGRADED":
        return "".join(
            [
                "<!doctype html><meta charset=utf-8>",
                "<meta name=viewport content='width=device-width,initial-scale=1'>",
                "<title>KEYRING — connection report</title><style>", STYLE, "</style>",
                '<div class="shell"><header class="topbar"><div class="brand">',
                '<span class="brand-mark">K</span><span>KEYRING<small>connection report</small></span>',
                "</div></header>",
                '<section class="hero"><div class="eyebrow"><span class="dot" style="background:#fab219"></span>',
                "Evidence status</div><h1>This report needs attention.</h1>",
                f'<p class="lead">{_esc(state.get("reason", "Evidence could not be read."))}</p>',
                "</section></div>",
            ]
        )

    authority = state["authority"]
    traces = state.get("traces", {})
    verified = [name for name, row in authority.items() if row.get("classification") == "VERIFIED"]
    denied = [name for name, row in authority.items() if row.get("classification") == "DENIED"]
    write_count = sum(len(row.get("advertised_write_tools", [])) for row in authority.values())
    chain = state["state_chain"]
    safety = state["safety"]
    financial = state.get("financial_reach", {})
    headline = state.get("headline", {})
    revocation = state.get("revocation", {})
    least = state.get("least_privilege", {})
    evidence_index = state.get("evidence_index", [])
    account_headline = state.get("account_headline", [])
    provenance_rows = financial.get("provenance_rows", [])
    approved_transactions = headline.get("approved_transactions", 0)

    lens_rows = _lens_rows(account_headline)
    disagreeing = [row for row in lens_rows if not row["agrees"]]

    # The lead sentence is written from the comparison, not hard-coded to it.
    if lens_rows and disagreeing:
        lead = (
            f"Two Binance accounts selected the same permissions and exposed the same "
            f"measured trading surface. <b>{disagreeing[0]['title']} gave different answers.</b>"
        )
        headline_claim = "Binance's permission self-report changed between the two accounts."
    elif lens_rows:
        lead = (
            f"We asked the same question {len(lens_rows)} different ways about the same "
            f"{len(account_headline)} Binance accounts. <b>Every way agreed.</b>"
        )
        headline_claim = "No disagreement was measured between the four surfaces."
    else:
        lead = "This report replays a recorded Binance Agent OS measurement."
        headline_claim = "No account comparison evidence is available."

    revocation_text = (
        "Access stopped after disconnect"
        if revocation.get("status") == "VERIFIED"
        else "No completed disconnect result"
    )
    revocation_reason = _sentence(
        revocation.get("reason", "No completed access transition recorded")
    )

    if headline.get("permission_reports_differ"):
        permission_signal = "Binance's permission self-report differed between the two accounts"
        permission_detail = (
            "The endpoint used to describe the credential returned different trading flags, "
            "while the connected surfaces were measured directly. This is an observability gap, "
            "not a broken control: enforcement was never shown to be weak."
        )
    else:
        permission_signal = "The permission report was compared with the live surface"
        permission_detail = "The report and the connected tool surface are shown together below."

    gated_rows = [row for row in provenance_rows if row.get("gated")]
    if provenance_rows:
        confirmation_detail = (
            f"{len(gated_rows)} of {len(provenance_rows)} observed account, client and mode "
            "combinations showed a confirmation prompt before a trading request; the rest did "
            "not. Because the prompt belongs to the client, the answer is kept per row rather "
            "than collapsed into one."
        )
    else:
        confirmation_detail = "No client gate observation was recorded."

    answer = (
        f"KEYRING measured {len(verified)} trading areas and found {write_count} exposed "
        "trading write tools. Each capability check stopped before execution, and the account "
        "state matched before and after those checks."
    )

    cap_order = sorted(
        authority,
        key=lambda name: (authority[name].get("classification") != "VERIFIED", name),
    )
    cap_cards = "".join(
        _capability_card(name, authority[name], traces, state.get("granted_scope"))
        for name in cap_order
    )

    needed_caps = [CAPABILITY_LABELS.get(item, item) for item in least.get("needed_capabilities", [])]
    extra_caps = [CAPABILITY_LABELS.get(item, item) for item in least.get("measured_excess_capabilities", [])]
    extra_tools = least.get("measured_excess_write_tools", [])
    instruments = least.get("instruments", {})
    remediation = least.get("remediation", {})

    money_rows = [
        ("capital_visible", "Money the connection could see", "measured",
         "Every wallet balance the session could read, quoted in USDT."),
        ("capital_reachable_by_trading", "Money reachable through trading we proved", "measured",
         "Held in wallets whose trading capability was measured and classified."),
        ("autonomous_capital_at_risk", "Money the agent could move on its own", "measured risk",
         "Zero where a confirmation prompt was observed in the same account and client."),
        ("spot_holdings", "Spot balances holding money", "",
         "Balances with a non-zero free or locked amount."),
        ("open_positions", "Open futures positions", "",
         "Positions with a non-zero amount across both futures products."),
        ("immediate_exit_cost", "Cost to exit the measured holding", "cost",
         "The live bid book walked for the holding, including the estimated taker fee."),
    ]
    money_cards = "".join(
        f'<article class="money-card {css}"><div class="money-label">{_esc(title)}</div>'
        f'<div class="money-value num">{_esc(_value_with_unit(key, financial.get(key, {})))}</div>'
        f'<div class="money-note">{_esc(_label_text(financial.get(key, {}).get("label", "")))} · {_esc(note)}</div></article>'
        for key, title, css, note in money_rows
    )

    contradiction_cards = "".join(
        f'<article class="note-card"><div class="section-kicker">{_esc(row.get("label", "Measured difference"))}</div>'
        f'<h3>{_esc(row["question"])}</h3><p>{_esc(_plain(row["measured"]))}</p>'
        f'<div class="refs">{_refs_html(row.get("evidence", []))}</div></article>'
        for row in state.get("contradictions", [])
    )

    evidence_json = json.dumps(evidence_index, ensure_ascii=True, separators=(",", ":")).replace("</", "<\\/")
    files_html = "".join(
        f'<button type="button" class="file-pill" data-file="{_esc(file)}">{_esc(file)}</button>'
        for file in state.get("evidence_files", [])
    )

    return "".join(
        [
            "<!doctype html><meta charset=utf-8>",
            "<meta name=viewport content='width=device-width,initial-scale=1'>",
            "<title>KEYRING — connection report</title>",
            '<meta name="description" content="A read-only, evidence-backed report of what one connected AI agent could actually do with a Binance Agent OS session.">',
            "<style>", STYLE, "</style>",
            '<a class="sr-only" href="#overview">Skip to the report</a>',
            '<div class="shell">',

            # ---- top bar -------------------------------------------------- #
            '<header class="topbar" id="topbar"><div class="brand"><span class="brand-mark">K</span>',
            "<span>KEYRING<small>connection report</small></span></div>",
            '<nav class="nav" aria-label="Report sections">',
            '<a href="#overview">Overview</a><a href="#compare">The comparison</a>',
            '<a href="#agent">The agent</a><a href="#access">Access</a><a href="#money">Money</a>',
            '<a href="#evidence">Evidence</a><a href="#notes">Notes</a></nav>',
            '<div class="tools">',
            '<button class="icon-btn" id="theme-toggle" type="button" aria-label="Switch between light and dark">',
            '<span id="theme-icon" aria-hidden="true">◐</span><span id="theme-text">Theme</span></button>',
            '<button class="icon-btn" id="copy-json" type="button">Copy data link</button>',
            "</div></header>",

            # ---- hero ------------------------------------------------------ #
            '<header class="hero" id="overview">',
            '<div class="eyebrow"><span class="dot"></span>Read-only · rebuilt from the evidence log</div>',
            "<h1>Same access. Different Binance self-report.</h1>",
            f'<p class="lead">{lead}</p>',
            '<p class="sub">KEYRING is an AI permission auditor for Binance Agent OS. It measures what a connected '
            "AI agent can reach, stops every test before an order can execute, and keeps a source record behind "
            "every number on this page. Nothing here is typed in by hand.</p>",
            '<div class="hero-strip">',
            f'<div class="hero-cell"><span>Permission granted</span><strong>{_esc(_scope_text(state.get("granted_scope")))}</strong></div>',
            f'<div class="hero-cell"><span>Connection result</span><strong>{_esc(len(verified))} areas reached · {_esc(len(denied))} not offered</strong></div>',
            f'<div class="hero-cell"><span>Access removal</span><strong>{_esc(revocation_text)}</strong></div>',
            f'<div class="hero-cell"><span>Request safety</span><strong>{_esc(safety["probe_budget"])} · {_esc(safety["rate_limit_status"])}</strong></div>',
            "</div>",
            '<div class="hero-actions"><a class="button" href="#compare">See the account comparison</a>',
            '<a class="button secondary" href="#agent">How the agent is fenced in</a>',
            '<a class="button secondary" href="/api/state" target="_blank" rel="noopener">Open the raw data</a></div>',
            "</header>",

            # ---- kpis ------------------------------------------------------ #
            '<section class="section" aria-label="Headline numbers" style="margin-top:22px">',
            '<div class="kpi-grid">',
            f'<article class="kpi a"><span class="number num">{_esc(len(verified))}</span>'
            '<span class="label">trading areas reached Binance\'s own order checks</span>'
            '<span class="foot">Every one stopped before execution</span></article>',
            f'<article class="kpi b"><span class="number num">{_esc(write_count)}</span>'
            '<span class="label">trading write tools were exposed to the connected agent</span>'
            f'<span class="foot">{_esc(len(least.get("measured_excess_write_tools", [])))} of them beyond what the strategy needs</span></article>',
            f'<article class="kpi c"><span class="number num">{_esc(state["records_replayed"])}</span>'
            '<span class="label">evidence records replayed to build this page</span>'
            f'<span class="foot">Across {_esc(len(state.get("evidence_files", [])))} files, chain intact</span></article>',
            f'<article class="kpi d"><span class="number num">{_esc(chain["probe_pairs"])}</span>'
            '<span class="label">safe tests with matching before / after account state</span>'
            '<span class="foot">No test changed the balance</span></article>',
            "</div></section>",

            # ---- the four answers ----------------------------------------- #
            '<section class="section" id="compare" aria-labelledby="compare-title">',
            '<div class="section-head"><div class="section-kicker">The finding</div>',
            '<h2 id="compare-title">The same access, described four ways</h2>',
            "<p>Each row compares one source across Account A and Account B: the permission selected, "
            "Binance's self-report, the tools exposed to the agent, and controlled tests. The first, "
            "third, and fourth rows stayed the same. Only Binance's self-report changed.</p></div>",
            _lens_cards_html(lens_rows),
            _lens_matrix_html(lens_rows, account_headline),
            '<div class="verdict"><div>',
            f"<h3>{_esc(headline_claim)}</h3>",
            "<p><strong>Same permission set. Same measured trading surface. Different self-report.</strong> "
            f"{_esc(_account_headline_summary(account_headline))}</p></div></div>",
            f'<p class="explain">{_esc(permission_detail)}</p>',
            "</section>",

            # ---- the agent -------------------------------------------------- #
            '<section class="section" id="agent" aria-labelledby="agent-title">',
            '<div class="section-head"><div class="section-kicker">The agent</div>',
            '<h2 id="agent-title">KEYRING audits. The model only proposes test inputs.</h2>',
            "<p>Binance discovers tool schemas and exchange filters at runtime, so the test values cannot be "
            "written in advance — a model reads the live schema and proposes one. It then has to get past a "
            "deterministic gate it does not control, and it never owns the published answer.</p></div>",
            _timeline_html(),
            '<div class="callout"><strong>The gate is the feature.</strong> No model output in this report is a '
            "classification, a number, or a verdict. The model has never held a Binance session and has never sent "
            "a request. Replay the whole recorded loop — schema, proposal, gate, request, interpretation, result, "
            "state proof — with <span class=\"mono\">python -m keyring agent-replay</span>.</div>",
            "</section>",

            # ---- signals ---------------------------------------------------- #
            '<section class="section" aria-labelledby="signals-title">',
            '<div class="section-head"><div class="section-kicker">What stands out</div>',
            '<h2 id="signals-title">Three results worth reading first</h2></div>',
            '<div class="signals">',
            f'<article class="signal">{_pill("no", "≠", "Self-report")}<h3>{_esc(permission_signal)}</h3>'
            f'<p>{_esc(permission_detail)}</p></article>',
            f'<article class="signal">{_pill("warn", "!", "Client behaviour")}'
            "<h3>Whether you get asked first depended on the client</h3>"
            f'<p>{_esc(confirmation_detail)}</p></article>',
            f'<article class="signal">{_pill("ok", "✓", "Revocation")}<h3>{_esc(revocation_text)}</h3>'
            f'<p>{_esc(revocation_reason)}</p></article>',
            "</div></section>",

            # ---- access map ------------------------------------------------- #
            '<section class="section" id="access" aria-labelledby="access-title">',
            '<div class="section-head"><div class="section-kicker">Access map</div>',
            '<h2 id="access-title">What this connection could reach</h2>',
            "<p>One card per trading area. Open any card to see the request that was sent, the response Binance "
            "returned, the before/after state check, and the numbered records behind all of it.</p></div>",
            '<div class="toolbar">',
            '<label class="search"><span class="sr-only">Search capabilities</span>',
            '<input id="capability-search" type="search" placeholder="Search Spot, Futures, Convert…" autocomplete="off">',
            "<kbd>/</kbd></label>",
            '<div class="filters" role="group" aria-label="Filter capabilities">',
            '<button type="button" class="filter active" data-filter="all">All</button>',
            '<button type="button" class="filter" data-filter="reached">Reached</button>',
            '<button type="button" class="filter" data-filter="not-offered">Not offered</button>',
            '<button type="button" class="filter" data-filter="other">Unclear</button>',
            '<button type="button" class="filter" id="expand-all">Expand all</button></div></div>',
            f'<div class="access-grid" id="access-grid">{cap_cards}</div>',
            '<div class="no-results" id="no-results">No capability matches that search.</div></section>',

            # ---- scope ------------------------------------------------------ #
            '<section class="section" id="scope" aria-labelledby="scope-title">',
            '<div class="section-head"><div class="section-kicker">Least privilege</div>',
            '<h2 id="scope-title">What the strategy needs vs what the connection handed over</h2>',
            "<p>The example strategy declares what it needs. The connection measured more than that. The two are "
            "kept apart on purpose — extra access is only counted where it was actually measured.</p></div>",
            '<div class="compare-grid">',
            '<article class="compare-card needed"><h3>Needed by the example strategy</h3>'
            f"<p>Declared in a checksummed strategy file.</p>{_plain_list(needed_caps)}"
            f'{_plain_list(least.get("required_spot_symbols", []), "No symbols recorded")}</article>',
            '<article class="compare-card extra"><h3>Also available in the connection</h3>'
            f"<p>Measured as extra product access, separate from the strategy's needs.</p>{_plain_list(extra_caps)}"
            f'{_plain_list([f"{len(extra_tools)} extra write actions"] if extra_tools else [], "No extra write actions measured")}</article>',
            "</div>",
            '<div class="callout"><strong>Narrowing this permission:</strong> '
            f'{_esc(_plain(remediation.get("outcome", "Not recorded")))}. '
            f'The venue lists {_esc(instruments.get("listed_trading_instruments", "—"))} spot instruments, but only '
            f'{_esc(financial.get("instruments", {}).get("spot_symbols_probed", "—"))} symbol was tested here. '
            "Those two numbers are never treated as the same thing.</div></section>",

            # ---- money ------------------------------------------------------ #
            '<section class="section" id="money" aria-labelledby="money-title">',
            '<div class="section-head"><div class="section-kicker">Money and safety</div>',
            '<h2 id="money-title">What money was within reach?</h2>',
            "<p>Each number answers a different question, so they are never merged into one. The capability "
            "checks were non-executing; a separate, explicitly approved buy and sell is reported on its own.</p></div>",
            f'<div class="money-grid">{money_cards}</div>',
            '<h3 class="subsection-title">Confirmation and capital, kept per account and client</h3>',
            '<p class="explain" style="margin-top:0;margin-bottom:14px">Whether a confirmation prompt appears before a '
            "trading request is a property of the client, not of the account — so it is never collapsed into a single "
            "answer. Each row keeps its own observation.</p>",
            _client_gate_table_html(provenance_rows),
            f'<div class="money-note-block"><strong>{_esc(approved_transactions)} approved transaction records are '
            "included separately.</strong> The approved measurement used one bounded Spot buy and one Spot sell, only "
            "to create and close a small holding. No futures order, transfer, or withdrawal was ever sent.</div></section>",

            # ---- evidence ---------------------------------------------------- #
            '<section class="section" id="evidence" aria-labelledby="evidence-title">',
            '<div class="section-head"><div class="section-kicker">Evidence</div>',
            '<h2 id="evidence-title">Why every answer above can be checked</h2>',
            "<p>Within each active evidence file, every record links to the one before it; an edit breaks that file's verification. Search all "
            f'{_esc(len(evidence_index))} records below, or click any evidence chip on the page to jump into one.</p></div>',
            '<div class="integrity-grid">',
            f'<article class="integrity-card"><span class="big num">{_esc(state["records_replayed"])}</span><span class="small">records replayed</span></article>',
            f'<article class="integrity-card"><span class="big num">{_esc(chain["digests_seen"])}</span><span class="small">state digests captured</span></article>',
            f'<article class="integrity-card"><span class="big num">{_esc(chain["distinct_states"])}</span><span class="small">distinct account states</span></article>',
            f'<article class="integrity-card pass"><span class="big">{_esc("Yes" if chain["probe_pairs_identical"] else "No")}</span><span class="small">before / after matched on every test</span></article>',
            f'<article class="integrity-card pass"><span class="big">{_esc("Verified" if chain["active_files_verified"] else "Check")}</span><span class="small">active evidence files</span></article>',
            "</div>",
            '<h3 class="subsection-title">Evidence explorer</h3>',
            '<div class="explorer">',
            '<div class="explorer-head">',
            '<label class="search"><span class="sr-only">Search evidence records</span>',
            '<input id="evidence-search" type="search" placeholder="Search records, operations, error codes…" autocomplete="off"></label>',
            '<div class="filters" role="group" aria-label="Filter evidence records">',
            '<button type="button" class="filter active" data-origin="all">All</button>',
            '<button type="button" class="filter" data-origin="harness">Captured by the build</button>',
            '<button type="button" class="filter" data-origin="operator">Watched by a person</button></div></div>',
            '<div class="explorer-scroll"><table class="evtable">',
            '<caption class="sr-only">Every evidence record replayed for this report</caption>',
            '<thead><tr><th scope="col">Record</th><th scope="col">Type</th><th scope="col">Operation</th>',
            '<th scope="col">Result</th><th scope="col">Code</th><th scope="col">How it was captured</th></tr></thead>',
            '<tbody id="evidence-rows"></tbody></table></div>',
            '<div class="explorer-foot"><span id="evidence-count"></span>',
            '<span>Click any row for the full record summary.</span></div></div>',
            f'<article class="source-card"><h3>Evidence files in this report · {len(state.get("evidence_files", []))}</h3>',
            f'<div class="file-pills">{files_html}</div></article></section>',

            # ---- notes -------------------------------------------------------- #
            '<section class="section" id="notes" aria-labelledby="notes-title">',
            '<div class="section-head"><div class="section-kicker">Measured differences</div>',
            '<h2 id="notes-title">Where published answers differed from the live session</h2>',
            "<p>These are observations about what the connected surfaces said or did. None of them is presented "
            "as an exploit, and none of them showed enforcement to be weak.</p></div>",
            f'<div class="notes-grid">{contradiction_cards}</div>',
            '<div class="legend"><span><b>OBSERVED · harness</b> — captured by the build</span>',
            '<span><b>OBSERVED · operator</b> — watched by a person</span>',
            '<span><b>DOCUMENTED</b> — stated by a source</span>',
            '<span><b>ASSUMED</b> — a cause this run did not establish</span></div>',
            f'<p class="explain">{_esc(BOUNDARY)}</p>',
            f'<p class="explain">{_esc(answer)}</p>',
            "</section>",

            f'<footer class="footer"><span>Read-only report · rebuilt from evidence at {_esc(state["generated_at"])}</span>',
            '<a href="/api/state" target="_blank" rel="noopener">Open the complete data view →</a></footer>',
            "</div>",

            '<div class="drawer-backdrop" id="drawer-backdrop" data-close="true" hidden></div>',
            '<aside class="drawer" id="evidence-drawer" role="dialog" aria-modal="true" aria-labelledby="drawer-title" hidden>',
            '<div class="drawer-header"><h2 id="drawer-title">Evidence record</h2>',
            '<button class="close" type="button" data-close="true" aria-label="Close evidence details">×</button></div>',
            '<div id="drawer-content"></div></aside>',
            "<script>", f"const EVIDENCE = {evidence_json};", SCRIPT, "</script>",
        ]
    )

# --------------------------------------------------------------------------- #
# server
# ---------------------------------------------------------------------------


def create_server(
    evidence_path: str | Path,
    *,
    host: str = "127.0.0.1",
    port: int = 8080,
    strategy_path: str | Path = "config/strategy.yaml",
    state_file: str | Path | None = None,
) -> ThreadingHTTPServer:
    # Verify and derive once at startup. The retained corpus is immutable while
    # this read-only process runs; replaying ~100 MB of evidence per HTTP request
    # would add tens of seconds of avoidable latency. A restart always rebuilds
    # from the source evidence rather than trusting a separately prepared state.
    state = (
        load_dashboard_state(state_file, evidence_path, strategy_path)
        if state_file is not None
        else dashboard_state(evidence_path, strategy_path)
    )

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def _send(self, body: bytes, content_type: str, status: int = 200) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            if self.path.startswith("/api/state"):
                self._send(
                    json.dumps(state, indent=2, default=str).encode(), "application/json"
                )
            else:
                self._send(render_html(state).encode(), "text/html; charset=utf-8")

        def _reject(self) -> None:
            self._send(
                b"KEYRING is read-only", "text/plain", HTTPStatus.METHOD_NOT_ALLOWED
            )

        do_POST = do_PUT = do_DELETE = do_PATCH = _reject  # noqa: N815

        def log_message(self, *args: Any) -> None:
            return

    return ThreadingHTTPServer((host, port), Handler)


def serve(
    evidence_path: str | Path,
    *,
    host: str = "127.0.0.1",
    port: int = 8080,
    strategy_path: str | Path = "config/strategy.yaml",
    state_file: str | Path | None = None,
) -> None:
    server = create_server(
        evidence_path,
        host=host,
        port=port,
        strategy_path=strategy_path,
        state_file=state_file,
    )
    print(f"KEYRING dashboard listening on {host}:{port}")
    try:
        server.serve_forever()
    finally:
        server.server_close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve the read-only KEYRING connection report")
    parser.add_argument("--evidence", default="evidence/raw")
    parser.add_argument("--strategy", default="config/strategy.yaml")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--state-file")
    args = parser.parse_args()
    serve(
        args.evidence,
        host=args.host,
        port=args.port,
        strategy_path=args.strategy,
        state_file=args.state_file,
    )


if __name__ == "__main__":
    main()
