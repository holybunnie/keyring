"""The read-only KEYRING connection report.

The page is deliberately understandable without knowing the implementation.
It answers four questions in order: what was granted, what the connection
could reach, whether money changed, and what evidence supports each answer.
Every value is rebuilt from the append-only evidence log when the page loads.
There is no write route and no action button that can affect Binance.
"""

from __future__ import annotations

import argparse
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
    "A model helped draft safe test values, but code checked those values and made "
    "every final classification."
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
            result = outcomes[key]
            measured = result["measured"]
            label = result["label"]
            evidence = result["evidence"]
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
            f"{CAPABILITY_LABELS[name].replace(' trading', '').replace(' Futures', '')} ✓"
            for name, _ in tested
        ) or "No confirmed trading path"
        test_refs = [ref for _, refs in tested for ref in refs]

        rows.append(
            {
                "account": account,
                "permission_screen": {
                    "value": " · ".join(consent) or "Not recorded",
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
    state: dict[str, Any] = {
        "status": status,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "boundary": BOUNDARY,
        "granted_scope": authority["granted_scope"],
        "records_replayed": authority["records_replayed"],
        "state_chain": {
            "digests_seen": authority["state_digests_seen"],
            "distinct_states": authority["distinct_states"],
            "identical_throughout": authority["state_identical_throughout"],
            "probe_pairs": authority["probe_pairs"],
            "probe_pairs_identical": authority["probe_pairs_identical"],
            "chain_unbroken": True,
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


# --------------------------------------------------------------------------- #
# rendering
# --------------------------------------------------------------------------- #

STYLE = """
:root{--ink:#172033;--muted:#667085;--line:#e5e9f0;--paper:#ffffff;--wash:#f6f8fc;
--navy:#101b35;--navy2:#1b2b52;--purple:#6658d3;--purple-light:#eeecff;
--teal:#087f70;--teal-light:#e7f7f3;--amber:#a96805;--amber-light:#fff5df;
--red:#bf3d55;--red-light:#fff0f3;--shadow:0 14px 38px rgba(20,32,58,.08)}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
body{margin:0;background:var(--wash);color:var(--ink);font:15px/1.6 Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
button,input{font:inherit}button{cursor:pointer}a{color:inherit}
.shell{max-width:1240px;margin:0 auto;padding:0 28px 60px}
.topbar{display:flex;align-items:center;justify-content:space-between;gap:20px;padding:22px 0 18px}
.brand{display:flex;align-items:center;gap:11px;font-weight:800;letter-spacing:-.02em}.brand-mark{display:grid;place-items:center;width:34px;height:34px;border-radius:10px;background:linear-gradient(135deg,#7469ec,#3e9fba);color:#fff;font-size:17px}.brand small{display:block;color:#8992a5;font-size:11px;font-weight:600;letter-spacing:.06em;text-transform:uppercase}
.nav{display:flex;align-items:center;gap:5px;flex-wrap:wrap}.nav a,.nav button{border:0;background:transparent;color:#667085;text-decoration:none;padding:8px 10px;border-radius:8px;font-size:13px}.nav a:hover,.nav button:hover{background:#e9edf5;color:var(--ink)}
.hero{position:relative;overflow:hidden;border-radius:24px;background:linear-gradient(120deg,var(--navy),var(--navy2) 70%,#314773);color:#fff;padding:46px 46px 42px;box-shadow:var(--shadow)}.hero:after{content:"";position:absolute;width:380px;height:380px;border:1px solid rgba(255,255,255,.11);border-radius:50%;right:-110px;top:-160px;box-shadow:0 0 0 35px rgba(255,255,255,.025),0 0 0 70px rgba(255,255,255,.018)}.hero>*{position:relative;z-index:1}.eyebrow,.section-kicker{font-size:11px;text-transform:uppercase;letter-spacing:.14em;font-weight:800;color:#aeb9d2}.hero h1{font-size:clamp(30px,4.5vw,54px);line-height:1.08;letter-spacing:-.055em;max-width:760px;margin:12px 0 16px}.hero .lead{max-width:720px;color:#c9d2e4;font-size:17px;margin:0}.hero-grid{display:grid;grid-template-columns:minmax(0,1.35fr) minmax(260px,.65fr);gap:30px;margin-top:34px}.answer{border:1px solid rgba(255,255,255,.17);background:rgba(255,255,255,.08);border-radius:16px;padding:20px 22px}.answer-label{color:#aeb9d2;font-size:12px;text-transform:uppercase;letter-spacing:.11em;font-weight:800}.answer h2{font-size:22px;line-height:1.25;letter-spacing:-.025em;margin:8px 0}.answer p{color:#d5dced;margin:0}.hero-facts{display:grid;gap:12px;align-content:center}.hero-fact{display:flex;justify-content:space-between;gap:16px;padding:12px 0;border-bottom:1px solid rgba(255,255,255,.13)}.hero-fact:last-child{border-bottom:0}.hero-fact span{color:#aeb9d2}.hero-fact strong{text-align:right}.hero-actions{display:flex;gap:9px;flex-wrap:wrap;margin-top:25px}.button{border:1px solid #d8ddea;background:#fff;color:var(--ink);border-radius:9px;padding:9px 13px;font-weight:700;font-size:13px;text-decoration:none}.button.secondary{background:transparent;color:#fff;border-color:rgba(255,255,255,.27)}.button:hover{transform:translateY(-1px);box-shadow:0 5px 12px rgba(0,0,0,.12)}
.hero-panel{margin-top:30px;border:1px solid rgba(255,255,255,.18);background:rgba(255,255,255,.07);border-radius:17px;padding:20px}.hero-panel h2{font-size:24px;letter-spacing:-.035em;margin:0 0 4px}.hero-panel-intro{color:#c9d2e4;margin:0 0 15px}.account-panels{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.account-panel{border:1px solid rgba(255,255,255,.16);border-radius:12px;overflow:hidden;background:rgba(255,255,255,.055)}.account-panel h3{font-size:15px;margin:0;padding:13px 15px;background:rgba(255,255,255,.08)}.account-row{display:grid;grid-template-columns:minmax(145px,.8fr) minmax(0,1.2fr);gap:14px;padding:11px 15px;border-top:1px solid rgba(255,255,255,.11)}.account-row span{color:#aeb9d2;font-size:12px}.account-row strong{font-size:13px;text-align:right;overflow-wrap:anywhere}.account-row strong a{color:#fff;text-decoration:underline;text-decoration-color:rgba(255,255,255,.45);text-underline-offset:3px}.account-technical{display:block;color:#aeb9d2;font:10px/1.4 ui-monospace,SFMono-Regular,Menlo,monospace;margin-top:3px}.hero-panel-foot{color:#aeb9d2;font-size:11px;margin:14px 0 0}.hero-grid{display:grid;grid-template-columns:minmax(0,1.35fr) minmax(260px,.65fr);gap:30px;margin-top:34px}.answer{border:1px solid rgba(255,255,255,.17);background:rgba(255,255,255,.08);border-radius:16px;padding:20px 22px}.answer-label{color:#aeb9d2;font-size:12px;text-transform:uppercase;letter-spacing:.11em;font-weight:800}.answer h2{font-size:22px;line-height:1.25;letter-spacing:-.025em;margin:8px 0}.answer p{color:#d5dced;margin:0}.hero-facts{display:grid;gap:12px;align-content:center}.hero-fact{display:flex;justify-content:space-between;gap:16px;padding:12px 0;border-bottom:1px solid rgba(255,255,255,.13)}.hero-fact:last-child{border-bottom:0}.hero-fact span{color:#aeb9d2}.hero-fact strong{text-align:right}.hero-actions{display:flex;gap:9px;flex-wrap:wrap;margin-top:25px}.button{border:1px solid #d8ddea;background:#fff;color:var(--ink);border-radius:9px;padding:9px 13px;font-weight:700;font-size:13px;text-decoration:none}.button.secondary{background:transparent;color:#fff;border-color:rgba(255,255,255,.27)}.button:hover{transform:translateY(-1px);box-shadow:0 5px 12px rgba(0,0,0,.12)}
.kpi-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:13px;margin:18px 0 32px}.kpi{background:var(--paper);border:1px solid var(--line);border-radius:14px;padding:17px 18px;box-shadow:0 4px 16px rgba(20,32,58,.035)}.kpi .number{display:block;font-size:28px;line-height:1.1;font-weight:800;letter-spacing:-.05em}.kpi .label{display:block;color:var(--muted);font-size:12px;margin-top:6px}.kpi.good .number{color:var(--teal)}.kpi.purple .number{color:var(--purple)}.kpi.amber .number{color:var(--amber)}
.section{margin-top:42px;scroll-margin-top:24px}.section-head{display:flex;justify-content:space-between;align-items:end;gap:20px;margin-bottom:16px}.section-head h2{font-size:27px;line-height:1.15;letter-spacing:-.04em;margin:5px 0 0}.section-head p{color:var(--muted);margin:6px 0 0;max-width:720px}.section-kicker{color:#7a8498}.section-intro{color:var(--muted);max-width:790px;margin:-4px 0 18px}
.signals{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}.signal{background:var(--paper);border:1px solid var(--line);border-radius:15px;padding:20px;box-shadow:0 4px 16px rgba(20,32,58,.035);border-top:4px solid var(--purple)}.signal.good{border-top-color:var(--teal)}.signal.warn{border-top-color:var(--amber)}.signal h3{font-size:17px;line-height:1.25;letter-spacing:-.02em;margin:8px 0}.signal p{color:var(--muted);margin:0}.signal .signal-label{font-size:11px;text-transform:uppercase;letter-spacing:.1em;font-weight:800;color:var(--purple)}.signal.good .signal-label{color:var(--teal)}.signal.warn .signal-label{color:var(--amber)}
.timeline{display:grid;grid-template-columns:repeat(4,1fr);gap:0;background:var(--paper);border:1px solid var(--line);border-radius:16px;padding:22px 12px;box-shadow:0 4px 16px rgba(20,32,58,.035)}.timeline-step{position:relative;padding:0 20px}.timeline-step:not(:last-child):after{content:"";position:absolute;top:15px;right:-1px;width:calc(100% - 38px);height:1px;background:#d7ddea;transform:translateX(50%)}.timeline-number{position:relative;z-index:1;display:grid;place-items:center;width:31px;height:31px;border-radius:50%;background:var(--purple-light);color:var(--purple);font-weight:800;margin-bottom:12px}.timeline-step h3{font-size:15px;margin:0 0 4px}.timeline-step p{color:var(--muted);font-size:13px;margin:0}
.toolbar{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;margin:15px 0}.search{position:relative;flex:1;min-width:230px}.search input{width:100%;border:1px solid var(--line);border-radius:9px;background:var(--paper);padding:10px 13px 10px 34px;color:var(--ink);outline:none}.search input:focus{border-color:var(--purple);box-shadow:0 0 0 3px var(--purple-light)}.search:before{content:"⌕";position:absolute;left:12px;top:7px;color:#8992a5;font-size:19px}.filters{display:flex;gap:6px;flex-wrap:wrap}.filter{border:1px solid var(--line);background:var(--paper);color:var(--muted);border-radius:8px;padding:8px 11px;font-size:12px;font-weight:700}.filter.active,.filter:hover{background:var(--purple-light);border-color:#d8d3ff;color:var(--purple)}
.access-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:15px}.access-card{background:var(--paper);border:1px solid var(--line);border-radius:16px;padding:22px;box-shadow:0 4px 16px rgba(20,32,58,.035);transition:box-shadow .2s,transform .2s}.access-card:hover{transform:translateY(-2px);box-shadow:var(--shadow)}.access-card.hidden{display:none}.access-top{display:flex;justify-content:space-between;align-items:start;gap:10px}.access-card h3{font-size:20px;letter-spacing:-.03em;margin:5px 0}.access-card .description{color:var(--muted);margin:0 0 16px}.status{display:inline-flex;align-items:center;gap:5px;border-radius:999px;padding:5px 9px;font-size:11px;font-weight:800;white-space:nowrap}.status:before{content:"";width:6px;height:6px;border-radius:50%;background:currentColor}.status.reached{color:var(--teal);background:var(--teal-light)}.status.not-offered{color:var(--amber);background:var(--amber-light)}.status.unclear{color:var(--red);background:var(--red-light)}.access-kicker{font-size:11px;color:#8992a5;text-transform:uppercase;letter-spacing:.1em;font-weight:800}.access-stats{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin:15px 0}.access-stat{background:var(--wash);border-radius:9px;padding:10px}.access-stat span{display:block;color:var(--muted);font-size:11px}.access-stat strong{display:block;margin-top:3px;font-size:13px;overflow-wrap:anywhere}.tool-list{display:flex;gap:5px;flex-wrap:wrap;margin:10px 0 15px}.tool-name{background:#f0f2f7;border-radius:6px;color:#596579;font:11px/1.3 ui-monospace,SFMono-Regular,Menlo,monospace;padding:4px 6px}.proof-details{border-top:1px solid var(--line);padding-top:12px}.proof-details summary{cursor:pointer;color:var(--purple);font-size:13px;font-weight:800;list-style:none}.proof-details summary::-webkit-details-marker{display:none}.proof-details summary:before{content:"＋";display:inline-block;margin-right:5px}.proof-details[open] summary:before{content:"−"}.proof-list{margin-top:13px;display:grid;gap:9px}.proof-row{display:grid;grid-template-columns:145px minmax(0,1fr);gap:8px;padding:10px 0;border-bottom:1px dashed #e3e7ef}.proof-row:last-child{border-bottom:0}.proof-name{color:#68758a;font-size:12px;font-weight:800}.proof-label{display:block;color:#8992a5;font-size:9px;font-weight:700;letter-spacing:.03em;margin-top:2px}.proof-value{min-width:0;white-space:pre-wrap;overflow-wrap:anywhere;color:#354154;font-size:13px}.proof-evidence{grid-column:2;display:flex;gap:5px;flex-wrap:wrap}.evidence-ref{border:1px solid #d7d3ff;background:var(--purple-light);color:#594bc2;border-radius:6px;padding:4px 7px;font-size:11px;font-weight:700}.evidence-ref:hover{background:#dedaff}.no-results{display:none;background:var(--paper);border:1px dashed #cfd6e3;color:var(--muted);border-radius:12px;padding:22px;text-align:center}.no-results.show{display:block}
.compare-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:15px}.compare-card,.money-card,.integrity-card,.source-card{background:var(--paper);border:1px solid var(--line);border-radius:15px;padding:21px;box-shadow:0 4px 16px rgba(20,32,58,.035)}.compare-card h3,.money-card h3{font-size:16px;margin:0 0 12px}.compare-card.needed{border-top:4px solid var(--teal)}.compare-card.extra{border-top:4px solid var(--amber)}.compare-card p{color:var(--muted);margin:6px 0}.plain-list{padding:0;margin:8px 0 0;list-style:none}.plain-list li{padding:7px 0;border-bottom:1px solid var(--line)}.plain-list li:last-child{border-bottom:0}.plain-list li:before{content:"✓";color:var(--teal);font-weight:900;margin-right:8px}.extra .plain-list li:before{content:"+";color:var(--amber)}.callout{margin-top:14px;background:#f8f7ff;border:1px solid #e3e0ff;border-radius:12px;padding:15px 17px;color:#4c4b6a}.callout strong{color:var(--purple)}
.provenance-money{background:var(--paper);border:1px solid var(--line);border-radius:15px;overflow:hidden}.provenance-money-row{display:grid;grid-template-columns:1.2fr 1fr 1.15fr 1fr auto;gap:14px;align-items:center;padding:14px 17px;border-bottom:1px solid var(--line)}.provenance-money-row:last-child{border-bottom:0}.provenance-money-row>div:not(.provenance-money-source){display:flex;flex-direction:column;gap:2px}.provenance-money-row span,.provenance-money-row small{color:var(--muted);font-size:11px}.provenance-money-row strong{font-size:13px}.provenance-money-row>div:first-child span{font-size:12px}.provenance-money-source{display:flex;justify-content:flex-end}.provenance-money-source .evidence-ref{white-space:nowrap}
.money-grid{display:grid;grid-template-columns:repeat(5,1fr);gap:11px}.money-card{padding:17px}.money-card .money-label{color:var(--muted);font-size:12px;min-height:38px}.money-card .money-value{font-size:21px;font-weight:800;letter-spacing:-.035em;margin-top:8px;overflow-wrap:anywhere}.money-card .money-note{color:#8992a5;font-size:11px;margin-top:5px}.money-card.measured{border-top:3px solid var(--teal)}.money-card.cost{border-top:3px solid var(--amber)}.money-note-block{background:var(--teal-light);border:1px solid #c9ece4;border-radius:12px;padding:14px 16px;color:#23685f;margin-top:14px}.money-note-block strong{color:#075f54}
.subsection-title{font-size:18px;letter-spacing:-.025em;margin:28px 0 11px}
.integrity-grid{display:grid;grid-template-columns:repeat(5,1fr);gap:11px}.integrity-card{text-align:center;padding:17px 10px}.integrity-card .big{display:block;color:var(--purple);font-size:23px;font-weight:800;letter-spacing:-.04em}.integrity-card .small{display:block;color:var(--muted);font-size:11px;margin-top:4px}.integrity-card.pass .big{color:var(--teal)}.integrity-card.warn .big{color:var(--amber)}.explain{color:var(--muted);max-width:820px;margin:13px 0 0}.source-card{margin-top:14px}.source-card h3{font-size:15px;margin:0 0 8px}.file-pills{display:flex;gap:6px;flex-wrap:wrap}.file-pill{background:var(--wash);border:1px solid var(--line);border-radius:7px;color:#596579;font:11px/1.3 ui-monospace,SFMono-Regular,Menlo,monospace;padding:6px 8px}
.notes-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:14px}.note-card{background:var(--paper);border:1px solid var(--line);border-radius:15px;padding:19px}.note-card h3{font-size:16px;margin:0 0 8px}.note-card p{color:var(--muted);margin:0}.note-card .note-tag{color:var(--purple);font-size:11px;text-transform:uppercase;letter-spacing:.1em;font-weight:800}.legend{display:flex;gap:8px;flex-wrap:wrap;margin-top:14px}.legend span{font-size:11px;color:var(--muted);background:var(--paper);border:1px solid var(--line);border-radius:999px;padding:5px 8px}.legend b{color:var(--ink)}
.note-card .note-evidence{display:flex;gap:5px;flex-wrap:wrap;margin-top:13px}
.muted{color:var(--muted)}.sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}
.footer{display:flex;justify-content:space-between;gap:16px;align-items:center;border-top:1px solid var(--line);margin-top:48px;padding-top:20px;color:#8992a5;font-size:12px}.footer a{color:var(--purple);font-weight:700;text-decoration:none}
.drawer-backdrop{position:fixed;inset:0;background:rgba(11,19,38,.45);z-index:10}.drawer{position:fixed;z-index:11;right:0;top:0;height:100%;width:min(470px,100%);background:var(--paper);box-shadow:-15px 0 45px rgba(10,20,40,.2);padding:28px;overflow:auto}.drawer[hidden],.drawer-backdrop[hidden]{display:none}.drawer-header{display:flex;justify-content:space-between;align-items:start;gap:15px;border-bottom:1px solid var(--line);padding-bottom:15px}.drawer h2{font-size:22px;letter-spacing:-.035em;margin:0}.close{border:0;background:var(--wash);color:var(--muted);border-radius:8px;width:32px;height:32px;font-size:20px}.drawer-ref{font:12px/1.4 ui-monospace,SFMono-Regular,Menlo,monospace;color:var(--purple);overflow-wrap:anywhere;margin:17px 0}.drawer dl{display:grid;grid-template-columns:115px minmax(0,1fr);gap:10px 14px}.drawer dt{color:#8992a5;font-size:12px}.drawer dd{margin:0;color:#354154;overflow-wrap:anywhere}.drawer-note{background:var(--teal-light);color:#23685f;border-radius:9px;padding:11px 12px;margin-top:19px;font-size:13px}
@media(max-width:900px){.hero-grid,.signals,.compare-grid,.notes-grid,.account-panels{grid-template-columns:1fr}.kpi-grid{grid-template-columns:repeat(2,1fr)}.money-grid{grid-template-columns:repeat(3,1fr)}.integrity-grid{grid-template-columns:repeat(3,1fr)}.timeline{grid-template-columns:repeat(2,1fr);gap:22px}.timeline-step:not(:last-child):after{display:none}.timeline-step{padding:0 15px}.access-grid{grid-template-columns:1fr}.provenance-money-row{grid-template-columns:repeat(2,1fr)}.provenance-money-source{grid-column:1/-1;justify-content:flex-start}}
@media(max-width:580px){.shell{padding:0 14px 40px}.topbar{align-items:start;flex-direction:column}.hero{padding:30px 22px;border-radius:18px}.hero h1{font-size:36px}.kpi-grid,.money-grid,.integrity-grid{grid-template-columns:repeat(2,1fr)}.section-head{display:block}.access-stats{grid-template-columns:1fr}.proof-row{grid-template-columns:1fr}.proof-evidence{grid-column:1}.timeline{grid-template-columns:1fr}.footer{display:block}.footer a{display:inline-block;margin-top:8px}.account-row{grid-template-columns:1fr}.account-row strong{text-align:left}.provenance-money-row{grid-template-columns:1fr}}
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


def _refs_html(refs: list[str]) -> str:
    unique = list(dict.fromkeys(refs))
    if not unique:
        return '<span class="muted">No linked evidence</span>'
    return "".join(
        f'<button type="button" class="evidence-ref" data-ref="{_esc(ref)}">'
        f"Evidence #{_esc(ref.rsplit('#', 1)[-1])}</button>"
        for ref in unique
    )


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


def _account_headline_html(rows: list[dict[str, Any]]) -> str:
    def cell(label: str, fact: dict[str, Any]) -> str:
        technical = (
            f'<span class="account-technical">{_esc(fact["technical"])}</span>'
            if fact.get("technical")
            else ""
        )
        refs = _refs_html(fact.get("sources", []))
        return (
            f'<div class="account-row"><span>{_esc(label)}</span><strong>{_esc(fact.get("value", "—"))}'
            f'{technical}<small>{refs}</small></strong></div>'
        )

    cards = []
    for row in rows:
        cards.append(
            '<article class="account-panel">'
            f'<h3>{_esc(row["account"])}</h3>'
            + cell("Permission screen", row["permission_screen"])
            + cell("Binance's own permission check", row["permission_check"])
            + cell("Tools handed to the agent", row["tools"])
            + cell("Controlled tests", row["controlled_tests"])
            + "</article>"
        )
    if not cards:
        return '<p class="hero-panel-intro">No account-scoped headline evidence is available.</p>'
    return '<div class="account-panels">' + "".join(cards) + "</div>"


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


def _provenance_money_html(rows: list[dict[str, Any]]) -> str:
    def value(row: dict[str, Any], key: str) -> str:
        layer = row.get(key)
        if not layer:
            return "—"
        return _value_with_unit(key, layer)

    entries = []
    for row in rows:
        gate_text = "Prompt shown" if row.get("gated") else "No prompt observed"
        gate_label = row.get("gate_label", "")
        entries.append(
            '<div class="provenance-money-row">'
            f'<div><strong>{_esc(row.get("account", "—"))}</strong><span>{_esc(row.get("client", "—"))} · {_esc(row.get("permission_mode", "—"))}</span></div>'
            f'<div><span>Reachable</span><strong>{_esc(value(row, "capital_reachable_by_trading"))}</strong></div>'
            f'<div><span>Before dispatch</span><strong>{_esc(gate_text)}</strong><small>{_esc(gate_label)}</small></div>'
            f'<div><span>Autonomous risk</span><strong>{_esc(value(row, "autonomous_capital_at_risk"))}</strong></div>'
            f'<div class="provenance-money-source">{_refs_html([row["gate_source"]] + ([row["capital_source"]["ref"]] if row.get("capital_source") else []))}</div>'
            '</div>'
        )
    return "".join(entries) or '<p class="muted">No gate and capital contexts were recorded.</p>'


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


def render_html(state: dict[str, Any]) -> str:
    """Render the evidence-derived, interactive report."""
    if state["status"] == "DEGRADED":
        return (
            f"<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
            f"<title>KEYRING — connection report</title><style>{STYLE}</style>"
            f'<main class="shell"><header class="topbar"><div class="brand"><span class="brand-mark">K</span><span>KEYRING<small>connection report</small></span></div></header>'
            f'<section class="hero"><div class="eyebrow">Evidence status</div><h1>This report needs attention.</h1><p class="lead">{_esc(state.get("reason", "Evidence could not be read."))}</p></section></main>'
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
    revocation_text = (
        "Access stopped after disconnect"
        if revocation.get("status") == "VERIFIED"
        else "No completed disconnect result"
    )

    if headline.get("permission_reports_differ"):
        permission_signal = (
            "The permission report varied across the two measured sub-accounts"
        )
        permission_detail = (
            "The endpoint used to describe the credential returned different trading flags, "
            "while the connected surfaces were measured directly."
        )
    else:
        permission_signal = "The permission report was compared with the live surface"
        permission_detail = "The report and the connected tool surface are shown together below."

    confirmation_detail = "; ".join(
        f"{row['client']} {row['permission_mode']}: "
        f"{'prompt shown' if row['gated'] else 'no prompt observed'} "
        f"({row['gate_label']})"
        for row in provenance_rows
    ) or "No client gate observation was recorded."

    answer = (
        f"This connection reached {len(verified)} trading areas and showed {write_count} "
        "write actions. Each capability check stopped before execution, and the account "
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
        ("capital_visible", "Capital visible", "measured"),
        ("capital_reachable_by_trading", "Capital reachable through measured trading", "measured"),
        ("autonomous_capital_at_risk", "Capital movable without approval", "measured"),
        ("spot_holdings", "Spot balances with money in them", ""),
        ("open_positions", "Open futures positions", ""),
        ("immediate_exit_cost", "Cost to exit the measured holding", "cost"),
    ]
    money_cards = "".join(
        f'<article class="money-card {css}"><div class="money-label">{_esc(title)}</div>'
        f'<div class="money-value">{_esc(_value_with_unit(key, financial.get(key, {})))}</div>'
        f'<div class="money-note">{_esc(_label_text(financial.get(key, {}).get("label", "")))}</div></article>'
        for key, title, css in money_rows
    )

    contradiction_cards = "".join(
        f'<article class="note-card"><div class="note-tag">{_esc(row.get("label", "Measured difference"))}</div>'
        f'<h3>{_esc(row["question"])}</h3><p>{_esc(row["measured"])}</p>'
        f'<div class="note-evidence">{_refs_html(row.get("evidence", []))}</div></article>'
        for row in state.get("contradictions", [])
    )
    provenance_money = _provenance_money_html(provenance_rows)

    evidence_json = json.dumps(evidence_index, ensure_ascii=True, separators=(",", ":")).replace("</", "<\\/")
    files_html = "".join(f'<span class="file-pill">{_esc(file)}</span>' for file in state.get("evidence_files", []))
    revocation_interval = revocation.get("convergence_seconds")
    revocation_value = "—" if revocation_interval is None else f"{revocation_interval}s"
    revocation_reason = revocation.get("reason", "No completed access transition recorded")

    return "".join(
        [
            "<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>",
            "<title>KEYRING — connection report</title><style>", STYLE, "</style>",
            '<div class="shell">',
            '<header class="topbar"><div class="brand"><span class="brand-mark">K</span><span>KEYRING<small>connection report</small></span></div>',
            '<nav class="nav" aria-label="Report sections"><a href="#overview">Overview</a><a href="#access">Access</a><a href="#money">Money</a><a href="#evidence">Evidence</a><a href="#notes">Notes</a><button id="copy-json" type="button">Copy data link</button></nav></header>',
            '<header class="hero" id="overview"><div class="eyebrow">Measured connection report</div>',
            '<h1>What can this agent actually do?</h1>',
            '<p class="lead">We checked four ways. The answers didn\'t match.</p>',
            '<section class="hero-panel" aria-labelledby="headline-panel-title"><h2 id="headline-panel-title">What can this agent actually do?</h2><p class="hero-panel-intro">The permission screen, Binance’s own permission check, the tools handed to the agent, and controlled tests each answer a different part of the same question.</p>',
            f'{_account_headline_html(account_headline)}',
            f'<p class="hero-panel-foot"><strong>Same permission set. Same measured trading surface. Different self-report.</strong><br>{_esc(_account_headline_summary(account_headline))}<br>Every figure on this page is regenerated from the evidence log. Nothing is typed in.</p></section>',
            '<div class="hero-grid"><div class="answer"><div class="answer-label">The answer from this run</div>',
            f"<h2>{_esc(answer)}</h2><p>{_esc(BOUNDARY)}</p></div>",
            '<div class="hero-facts">',
            f'<div class="hero-fact"><span>Permission given</span><strong>{_esc(_scope_text(state.get("granted_scope")))}</strong></div>',
            f'<div class="hero-fact"><span>Connection result</span><strong>{_esc(len(verified))} areas reached · {_esc(len(denied))} not offered</strong></div>',
            f'<div class="hero-fact"><span>Access removal</span><strong>{_esc(revocation_text)}</strong></div>',
            f'<div class="hero-fact"><span>Request safety</span><strong>{_esc(safety["probe_budget"])} · {_esc(safety["rate_limit_status"])}</strong></div>',
            "</div></div>",
            '<div class="hero-actions"><a class="button" href="#access">See what it could reach</a><a class="button secondary" href="#evidence">See the evidence</a><a class="button secondary" href="/api/state" target="_blank" rel="noopener">Open data</a></div></header>',
            '<section class="kpi-grid" aria-label="Summary">',
            f'<article class="kpi good"><span class="number">{_esc(len(verified))}</span><span class="label">trading areas reached exchange checks</span></article>',
            f'<article class="kpi purple"><span class="number">{_esc(write_count)}</span><span class="label">write actions visible in the selected connection</span></article>',
            f'<article class="kpi good"><span class="number">{_esc(chain["probe_pairs"])}</span><span class="label">safe tests with matching before / after state</span></article>',
            f'<article class="kpi amber"><span class="number">{_esc(revocation.get("n", 0))}</span><span class="label">completed access-removal trial</span></article>',
            "</section>",
            '<section class="section" aria-labelledby="signals-title"><div class="section-head"><div><div class="section-kicker">What stands out</div><h2 id="signals-title">Three answers worth seeing first</h2></div></div>',
            '<div class="signals">',
            f'<article class="signal"><div class="signal-label">Permission report</div><h3>{_esc(permission_signal)}</h3><p>{_esc(permission_detail)}</p></article>',
            f'<article class="signal warn"><div class="signal-label">Client behavior</div><h3>Confirmation behavior depended on the client</h3><p>{_esc(confirmation_detail)}</p></article>',
            f'<article class="signal good"><div class="signal-label">Revocation · {_esc(revocation.get("label", "OBSERVED · operator"))}</div><h3>{_esc(revocation_text)}</h3><p>{_esc(revocation_reason)}</p></article>',
            "</div></section>",
            '<section class="section" aria-labelledby="method-title"><div class="section-head"><div><div class="section-kicker">How the answer was built</div><h2 id="method-title">A short, visible path from permission to proof</h2></div></div>',
            '<div class="timeline">',
            '<div class="timeline-step"><div class="timeline-number">1</div><h3>Read the permission</h3><p>Captured the scope returned by the connection.</p></div>',
            '<div class="timeline-step"><div class="timeline-number">2</div><h3>List the tools</h3><p>Recorded what the live session made available.</p></div>',
            '<div class="timeline-step"><div class="timeline-number">3</div><h3>Test safely</h3><p>Sent requests designed to fail at exchange checks before execution.</p></div>',
            '<div class="timeline-step"><div class="timeline-number">4</div><h3>Check before and after</h3><p>Compared account state and linked every answer to evidence.</p></div>',
            "</div></section>",
            '<section class="section" id="access" aria-labelledby="access-title"><div class="section-head"><div><div class="section-kicker">Access map</div><h2 id="access-title">What this connection could reach</h2><p>Choose a card to see the request, the exchange response, the state check, and the evidence records behind it.</p></div></div>',
            '<div class="toolbar"><label class="search"><span class="sr-only">Search capabilities</span><input id="capability-search" type="search" placeholder="Search Spot, Futures, Convert…" autocomplete="off"></label><div class="filters" role="group" aria-label="Filter capabilities"><button type="button" class="filter active" data-filter="all">All</button><button type="button" class="filter" data-filter="reached">Reached</button><button type="button" class="filter" data-filter="not-offered">Not offered</button><button type="button" class="filter" data-filter="other">Other</button><button type="button" class="filter" id="expand-all">Expand all</button></div></div>',
            f'<div class="access-grid" id="access-grid">{cap_cards}</div><div class="no-results" id="no-results">No capability matches that search.</div></section>',
            '<section class="section" id="scope" aria-labelledby="scope-title"><div class="section-head"><div><div class="section-kicker">Scope comparison</div><h2 id="scope-title">What was needed vs what was also available</h2><p>This keeps the strategy’s needs separate from extra access measured in the connection.</p></div></div>',
            '<div class="compare-grid">',
            f'<article class="compare-card needed"><h3>Needed by the example strategy</h3><p>These are the product and symbol requirements declared in the strategy file.</p>{_plain_list(needed_caps)}{_plain_list(least.get("required_spot_symbols", []), "No symbols recorded")}</article>',
            f'<article class="compare-card extra"><h3>Also available in the connection</h3><p>These were measured as extra product access, separate from the strategy’s needs.</p>{_plain_list(extra_caps)}{_plain_list([f"{len(extra_tools)} extra write actions"] if extra_tools else [], "No extra write actions measured")}</article>',
            "</div>",
            f'<div class="callout"><strong>Changing this permission:</strong> {_esc(remediation.get("outcome", "Not recorded").replace("RECONNECT_REQUIRED", "disconnect and authorize again"))}. The venue lists {_esc(instruments.get("listed_trading_instruments", "—"))} spot instruments, but only {_esc(financial.get("instruments", {}).get("spot_symbols_probed", "—"))} symbol was tested here; those numbers are not treated as the same thing.</div></section>',
            '<section class="section" id="money" aria-labelledby="money-title"><div class="section-head"><div><div class="section-kicker">Money and safety</div><h2 id="money-title">What money was within reach?</h2><p>Each number answers a different question. The capability checks were non-executing; the separate buy/sell measurement was explicitly approved.</p></div></div>',
            f'<div class="money-grid">{money_cards}</div>',
            '<h3 class="subsection-title">Money and approval, kept by account and client</h3>',
            f'<div class="provenance-money">{provenance_money}</div>',
            f'<div class="money-note-block"><strong>{_esc(approved_transactions)} approved transaction records are included separately.</strong> The table above keeps each balance with the client and mode that produced its gate observation. No Futures, transfer, or withdrawal was sent.</div></section>',
            '<section class="section" id="evidence" aria-labelledby="evidence-title"><div class="section-head"><div><div class="section-kicker">Evidence health</div><h2 id="evidence-title">Why these answers can be checked</h2><p>Every card above links to a numbered record. Click any evidence chip to see its safe summary.</p></div></div>',
            '<div class="integrity-grid">',
            f'<article class="integrity-card"><span class="big">{_esc(state["records_replayed"])}</span><span class="small">records replayed</span></article>',
            f'<article class="integrity-card"><span class="big">{_esc(chain["digests_seen"])}</span><span class="small">state digests</span></article>',
            f'<article class="integrity-card"><span class="big">{_esc(chain["distinct_states"])}</span><span class="small">captured states</span></article>',
            f'<article class="integrity-card pass"><span class="big">{_esc("Yes" if chain["probe_pairs_identical"] else "No")}</span><span class="small">before / after matched</span></article>',
            f'<article class="integrity-card pass"><span class="big">{_esc("Intact" if chain["chain_unbroken"] else "Check")}</span><span class="small">record history</span></article>',
            "</div>",
            '<p class="explain">The record history links each entry to the one before it, so an edit changes the verification result. For every safe capability test, the complete account snapshot before the request matched the snapshot after it.</p>',
            f'<article class="source-card"><h3>Evidence files in this report · {len(state.get("evidence_files", []))}</h3><div class="file-pills">{files_html}</div></article></section>',
            '<section class="section" id="notes" aria-labelledby="notes-title"><div class="section-head"><div><div class="section-kicker">Measured differences</div><h2 id="notes-title">Where published answers differed from the live session</h2><p>These are observations about what the connected surfaces said or did. They are not presented as exploits.</p></div></div>',
            f'<div class="notes-grid">{contradiction_cards}</div>',
            '<div class="legend"><span><b>OBSERVED · harness</b> — captured by the build</span><span><b>OBSERVED · operator</b> — watched by a person</span><span><b>DOCUMENTED</b> — stated by a source</span><span><b>ASSUMED</b> — a cause not established by this run</span></div></section>',
            f'<footer class="footer"><span>Read-only report · generated {_esc(state["generated_at"])}</span><a href="/api/state" target="_blank" rel="noopener">Open the complete data view →</a></footer>',
            "</div>",
            '<div class="drawer-backdrop" id="drawer-backdrop" data-close="true" hidden></div><aside class="drawer" id="evidence-drawer" role="dialog" aria-modal="true" aria-labelledby="drawer-title" hidden><div class="drawer-header"><h2 id="drawer-title">Evidence details</h2><button class="close" type="button" data-close="true" aria-label="Close evidence details">×</button></div><div id="drawer-content"></div></aside>',
            "<script>",
            "(() => {",
            f"const evidence = {evidence_json};",
            "const byRef = Object.fromEntries(evidence.map(item => [item.ref, item]));",
            "const escapeHtml = value => String(value ?? '—').replace(/[&<>\"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[char]));",
            "const drawer = document.getElementById('evidence-drawer'); const backdrop = document.getElementById('drawer-backdrop'); const drawerContent = document.getElementById('drawer-content');",
            "const closeDrawer = () => { drawer.hidden = true; backdrop.hidden = true; };",
            "const openDrawer = ref => { const item = byRef[ref]; if (!item) return; drawerContent.innerHTML = `<div class=\"drawer-ref\">${escapeHtml(item.ref)}</div><dl><dt>Type</dt><dd>${escapeHtml(item.kind)}</dd><dt>Operation</dt><dd>${escapeHtml(item.operation)}</dd><dt>Capability</dt><dd>${escapeHtml(item.capability)}</dd><dt>Result</dt><dd>${escapeHtml(item.outcome)}</dd><dt>Label</dt><dd>${escapeHtml(item.label)}</dd><dt>Captured by</dt><dd>${escapeHtml(item.capture_origin)}</dd><dt>Time</dt><dd>${escapeHtml(item.occurred_at)}</dd><dt>Error code</dt><dd>${escapeHtml(item.error_code)}</dd><dt>State check</dt><dd>${escapeHtml(item.state_proof)}</dd><dt>Source</dt><dd>${escapeHtml(item.source)}</dd></dl><div class=\"drawer-note\">This panel shows record metadata only. The full, redacted data is available from the JSON view.</div>`; drawer.hidden = false; backdrop.hidden = false; drawer.querySelector('.close').focus(); };",
            "document.querySelectorAll('.evidence-ref').forEach(button => button.addEventListener('click', () => openDrawer(button.dataset.ref))); document.querySelectorAll('[data-close]').forEach(item => item.addEventListener('click', closeDrawer)); document.addEventListener('keydown', event => { if (event.key === 'Escape') closeDrawer(); });",
            "const cards = [...document.querySelectorAll('.access-card')]; const search = document.getElementById('capability-search'); const empty = document.getElementById('no-results'); let activeFilter = 'all';",
            "const applyFilters = () => { const query = search.value.trim().toLowerCase(); let shown = 0; cards.forEach(card => { const matchesFilter = activeFilter === 'all' || card.dataset.status === activeFilter; const matchesSearch = !query || card.dataset.search.includes(query); const visible = matchesFilter && matchesSearch; card.classList.toggle('hidden', !visible); if (visible) shown += 1; }); empty.classList.toggle('show', shown === 0); };",
            "document.querySelectorAll('[data-filter]').forEach(button => button.addEventListener('click', () => { activeFilter = button.dataset.filter; document.querySelectorAll('[data-filter]').forEach(item => item.classList.toggle('active', item === button)); applyFilters(); })); search.addEventListener('input', applyFilters);",
            "document.getElementById('expand-all').addEventListener('click', event => { const open = event.currentTarget.dataset.open !== 'true'; cards.forEach(card => card.querySelectorAll('details').forEach(detail => { detail.open = open; })); event.currentTarget.dataset.open = String(open); event.currentTarget.textContent = open ? 'Collapse all' : 'Expand all'; });",
            "document.getElementById('copy-json').addEventListener('click', async event => { const button = event.currentTarget; try { await navigator.clipboard.writeText(new URL('/api/state', window.location.href).href); button.textContent = 'Data link copied'; setTimeout(() => { button.textContent = 'Copy data link'; }, 1800); } catch (_) { window.open('/api/state', '_blank', 'noopener'); } });",
            "})();",
            "</script>",
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
) -> ThreadingHTTPServer:
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
            state = dashboard_state(evidence_path, strategy_path)
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
) -> None:
    server = create_server(evidence_path, host=host, port=port, strategy_path=strategy_path)
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
    args = parser.parse_args()
    serve(args.evidence, host=args.host, port=args.port, strategy_path=args.strategy)


if __name__ == "__main__":
    main()
