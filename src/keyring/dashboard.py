"""The read-only KEYRING dashboard.

Everything served here is derived from the append-only evidence log at request
time. Nothing is cached, nothing is hand-entered, and there is no write path:
the server answers GET and refuses everything else.

Part VII requires the probe budget and rate-limit health to be permanently
visible, so they sit in the header rather than on a sub-page. Part VI requires
every classification to expand into its proof chain, so each authority row is
expandable and each line of the chain names the evidence record it came from.
"""

from __future__ import annotations

import argparse
import html
import json
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .authority import derive
from .config import load_probe_config
from .evidence import EvidenceLog
from .financialreach import reach
from .leastprivilege import diff
from .revocation import revocation_summary
from .trace import trace

BOUNDARY = (
    "KEYRING's capability probes are deliberately non-executing. Every probe is "
    "constructed to terminate before execution, with financial state verified unchanged "
    "before and after. A separate financial-reach measurement may contain an explicitly "
    "approved, separately logged transaction. KEYRING follows Binance's own guidance: "
    "the MCP endpoint is never pasted into an AI chat and never opened in a browser. "
    "Claude may propose a probe or interpret an unmatched response; deterministic code "
    "validates proposals and owns every classification."
)

# DOCUMENTED: first-party source statements. The measured column is derived from
# the evidence log at request time, never written here.
CONTRADICTIONS = [
    {
        "question": "Can permissions be narrowed in place?",
        "source_a": "MCP docs: disconnect and reconnect to update",
        "source_b": "Launch blog: permissions reviewable or changeable under Account Management",
        "measured_from": "m0-5-permission-mutability",
    },
    {
        "question": "Is confirmation always required?",
        "source_a": "MCP docs: applies to every non-read action",
        "source_b": "Support FAQ: flows are designed to request confirmation",
        "measured_from": "client_gate_observation",
    },
]


def _evidence_dir(path: str | Path) -> Path:
    path = Path(path)
    return path if path.is_dir() else path.parent


def _safety(evidence_dir: Path) -> dict[str, Any]:
    """Part VII: probe budget and rate-limit health, derived from the log."""
    try:
        budgets = load_probe_config().model.budgets
        max_per_run = getattr(budgets, "max_probes_per_run", None)
    except Exception:  # noqa: BLE001 - a missing config must not take the page down
        max_per_run = None

    all_records: list[Any] = []
    status = "HEALTHY"
    for file in sorted(evidence_dir.glob("*.jsonl")):
        try:
            all_records.extend(EvidenceLog(file).records(verify=True))
        except Exception:  # noqa: BLE001 - an unverifiable file is reported below
            status = "EVIDENCE UNVERIFIABLE"

    latest_probe = max(
        (
            record
            for record in all_records
            if record.record_type == "capability_probe"
        ),
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
            status = "KILLED (418)"
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


def _measured_contradictions(evidence_dir: Path) -> list[dict[str, Any]]:
    outcomes: dict[str, str] = {}
    gate_default = None
    ungated_probe = False
    for file in sorted(evidence_dir.glob("*.jsonl")):
        try:
            records = EvidenceLog(file).records(verify=True)
        except Exception:  # noqa: BLE001
            continue
        for record in records:
            if record.run_id == "m0-5-permission-mutability":
                outcomes["m0-5-permission-mutability"] = record.outcome or "—"
            if record.operation == "client_gate_observation":
                mode = str(record.metadata.get("permission_mode", ""))
                if "manual" not in mode:
                    gate_default = record.gate
            if record.record_type == "capability_probe" and record.gate == "UNGATED":
                ungated_probe = True

    rows = []
    for entry in CONTRADICTIONS:
        key = entry["measured_from"]
        if key == "m0-5-permission-mutability":
            if key not in outcomes:
                continue
            measured, label = outcomes[key], "OBSERVED"
        elif key == "client_gate_observation":
            if gate_default is None:
                continue
            else:
                measured = (
                    "no confirmation in the tested client default"
                    if str(gate_default) .endswith("UNGATED")
                    else "confirmation observed in the tested client default"
                )
                label = "OBSERVED"
        elif key == "capability_probe":
            if not ungated_probe:
                continue
            measured, label = "an invocation reached Binance with no human click", "OBSERVED"
        else:
            continue
        rows.append({**entry, "measured": measured, "label": label})
    return rows


def dashboard_state(
    evidence_path: str | Path,
    strategy_path: str | Path = "config/strategy.yaml",
) -> dict[str, Any]:
    """Rebuild the entire dashboard from evidence. No cached or stored state."""
    evidence_dir = _evidence_dir(evidence_path)

    try:
        authority = derive(evidence_dir)
    except Exception as error:  # noqa: BLE001 - surfaced, never hidden
        return {
            "status": "DEGRADED",
            "reason": f"evidence could not be replayed: {error}",
            "boundary": BOUNDARY,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    verified = [
        name
        for name, row in authority["capabilities"].items()
        if row["classification"] == "VERIFIED"
    ]
    status = "MEASURED" if verified else "DEGRADED"

    state = {
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
            # derive() can only return after every evidence file has passed its
            # sequence, previous-hash, and record-hash checks.
            "chain_unbroken": True,
        },
        "safety": _safety(evidence_dir),
        "authority": authority["capabilities"],
        "contradictions": _measured_contradictions(evidence_dir),
    }
    all_records = []
    for file in sorted(evidence_dir.glob("*.jsonl")):
        all_records.extend(EvidenceLog(file).records(verify=True))
    state["revocation"] = revocation_summary(all_records)

    if status == "DEGRADED":
        state["reason"] = (
            "no capability has been probed and classified VERIFIED from this evidence; "
            "measured effective authority is not presented"
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
        # Keep the dashboard/API focused on the measured financial layers. The
        # analytical module may retain an unresolved internal field, but it is
        # not part of the public evidence view.
        state["financial_reach"] = {
            key: value
            for key, value in financial.items()
            if key != "futures_gross_notional_ceiling"
        }
    except Exception as error:  # noqa: BLE001
        state["financial_reach"] = {"error": str(error)}
    return state


# --------------------------------------------------------------------------- #
# rendering
# --------------------------------------------------------------------------- #

STYLE = """
:root{--bg:#0d1117;--fg:#e6edf3;--dim:#8b949e;--line:#30363d;--card:#161b22;
--ok:#3fb950;--warn:#d29922;--bad:#f85149;--info:#58a6ff}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
font:14px/1.55 ui-monospace,SFMono-Regular,Menlo,monospace;padding:24px}
h1{font-size:20px;margin:0 0 4px} h2{font-size:14px;margin:28px 0 10px;
color:var(--dim);text-transform:uppercase;letter-spacing:.09em}
.boundary{background:var(--card);border-left:3px solid var(--info);
padding:12px 16px;margin:14px 0 20px;color:var(--dim);max-width:900px}
.bar{display:flex;flex-wrap:wrap;gap:10px;margin-bottom:8px}
.chip{background:var(--card);border:1px solid var(--line);border-radius:6px;
padding:8px 12px} .chip b{color:var(--fg)} .chip span{color:var(--dim)}
table{border-collapse:collapse;width:100%;max-width:1100px}
th,td{text-align:left;padding:7px 10px;border-bottom:1px solid var(--line);
vertical-align:top} th{color:var(--dim);font-weight:400}
.VERIFIED{color:var(--ok)}.DENIED{color:var(--warn)}
details{background:var(--card);border:1px solid var(--line);border-radius:6px;
margin:6px 0;padding:8px 12px;max-width:1100px}
summary{cursor:pointer} .chain{margin-top:8px}
.chain div{display:grid;grid-template-columns:150px 1fr 120px 260px;gap:8px;
padding:3px 0;border-bottom:1px solid var(--line)}
.lbl{color:var(--dim)} pre{white-space:pre-wrap;margin:0}
.ok{color:var(--ok)}.bad{color:var(--bad)}.dim{color:var(--dim)}
"""


def _esc(value: Any) -> str:
    return html.escape(str(value))


def render_html(state: dict[str, Any]) -> str:
    if state["status"] == "DEGRADED":
        return (
            f"<!doctype html><meta charset=utf-8><title>KEYRING</title><style>{STYLE}</style>"
            f"<h1>KEYRING — DEGRADED</h1><div class=boundary>{_esc(state['boundary'])}</div>"
            f"<p class=dim>{_esc(state.get('reason', ''))}</p>"
        )

    safety = state["safety"]
    chain = state["state_chain"]
    parts = [
        f"<!doctype html><meta charset=utf-8><title>KEYRING</title><style>{STYLE}</style>",
        "<h1>KEYRING — measured effective authority</h1>",
        f"<div class=boundary>{_esc(state['boundary'])}</div>",
        "<div class=bar>",
        f"<div class=chip><span>probe budget</span> <b>{_esc(safety['probe_budget'])}</b></div>",
        f"<div class=chip><span>rate-limit status</span> <b>{_esc(safety['rate_limit_status'])}</b></div>",
        f"<div class=chip><span>last 429</span> <b>{_esc(safety['last_429'])}</b></div>",
        f"<div class=chip><span>grant</span> <b>{_esc(state['granted_scope'])}</b></div>",
        f"<div class=chip><span>state</span> <b class="
        f"{'ok' if chain['probe_pairs_identical'] and chain['chain_unbroken'] else 'bad'}>"
        f"{state['records_replayed']} records · {chain['digests_seen']} digests · "
        f"{chain['distinct_states']} snapshot states · "
        f"{chain['probe_pairs']} probe pairs identical · "
        f"{'chain unbroken' if chain['chain_unbroken'] else 'chain broken'}</b></div>",
        "</div>",
        "<h2>Effective authority — click a row for its proof chain</h2>",
    ]

    traces = state.get("traces", {})
    for name, row in sorted(state["authority"].items()):
        cls = row["classification"]
        tools = len(row["advertised_write_tools"])
        parts.append(
            f"<details><summary><b>{_esc(name.upper())}</b> — "
            f"<span class={cls}>{cls}</span> "
            f"<span class=dim>· {tools} write tool(s) advertised · "
            f"probe {_esc(row['probe_tool'] or 'none')} "
            f"{_esc(row['error_code'] or '')}</span></summary><div class=chain>"
        )
        for step in traces.get(name, {}).get("steps", []):
            parts.append(
                f"<div><span class=lbl>{_esc(step['step'])}</span>"
                f"<span>{_esc(step['value'])}</span>"
                f"<span class=lbl>{_esc(step['label'])}</span>"
                f"<span class=lbl>{_esc(step['evidence'])}</span></div>"
            )
        for note in row["notes"]:
            parts.append(f"<div><span class=lbl>note</span><span class=dim>{_esc(note)}</span></div>")
        parts.append("</div></details>")

    lp = state.get("least_privilege", {})
    if "error" not in lp:
        instruments = lp.get("instruments", {})
        parts += [
            "<h2>Least-privilege diff</h2><table>",
            "<tr><th>Layer</th><th>Value</th><th>Label</th></tr>",
            f"<tr><td>needed capabilities</td><td>{_esc(', '.join(lp['needed_capabilities']))}</td>"
            "<td>manifest, read not inferred</td></tr>",
            f"<tr><td>needed instruments</td><td>{_esc(len(lp['required_spot_symbols']))}"
            f" ({_esc(', '.join(lp['required_spot_symbols']))})</td><td>manifest</td></tr>",
            f"<tr><td>measured excess capabilities</td>"
            f"<td>{_esc(', '.join(lp['measured_excess_capabilities']) or 'none')}</td>"
            "<td>OBSERVED</td></tr>",
            f"<tr><td>measured excess write tools</td>"
            f"<td>{_esc(lp['measured_excess_write_tool_count'])}</td><td>OBSERVED</td></tr>",
            f"<tr><td>potential excess instruments</td>"
            f"<td>{_esc(instruments.get('potential_excess_count'))}</td>"
            f"<td>{_esc(instruments.get('label'))}</td></tr>",
            f"<tr><td>remediation cost</td><td>{_esc(lp['remediation']['outcome'])}</td>"
            f"<td>{_esc(lp['remediation']['label'])}</td></tr>",
            "</table>",
        ]

    fr = state.get("financial_reach", {})
    if "error" not in fr:
        parts += ["<h2>Financial reach, layered</h2><table>",
                  "<tr><th>Layer</th><th>Value</th><th>Label</th><th>Reason</th></tr>"]
        for key, title in [
            ("capital_visible", "capital visible"),
            ("capital_reachable_by_trading", "capital reachable by trading"),
            ("autonomous_capital_at_risk", "autonomous capital at risk"),
            ("spot_holdings", "spot holdings"),
            ("immediate_exit_cost", "immediate exit cost"),
        ]:
            layer = fr.get(key, {})
            value = layer.get("value")
            parts.append(
                f"<tr><td>{_esc(title)}</td>"
                f"<td>{_esc('—' if value is None else value)}</td>"
                f"<td class={_esc(layer.get('label'))}>{_esc(layer.get('label'))}</td>"
                f"<td class=dim>{_esc(layer.get('reason'))}</td></tr>"
            )
        parts.append("</table>")

    revocation = state.get("revocation")
    if isinstance(revocation, dict):
        parts += [
            "<h2>Revocation</h2><table>",
            "<tr><th>Status</th><th>Trials</th><th>Convergence</th><th>Reason</th></tr>",
            f"<tr><td class={_esc(revocation.get('label'))}>{_esc(revocation.get('status'))}</td>"
            f"<td>{_esc(revocation.get('n'))}</td>"
            f"<td>{_esc(revocation.get('convergence_seconds') if revocation.get('convergence_seconds') is not None else '—')}</td>"
            f"<td class=dim>{_esc(revocation.get('reason'))}</td></tr>",
            "</table>",
        ]

    parts += ["<h2>First-party contradictions, measured</h2><table>",
              "<tr><th>Question</th><th>Source A</th><th>Source B</th><th>Measured</th></tr>"]
    for row in state["contradictions"]:
        parts.append(
            f"<tr><td>{_esc(row['question'])}</td><td class=dim>{_esc(row['source_a'])}</td>"
            f"<td class=dim>{_esc(row['source_b'])}</td>"
            f"<td>{_esc(row['measured'])}<br><span class=lbl>{_esc(row['label'])}</span></td></tr>"
        )
    parts.append("</table>")
    parts.append(
        f"<p class=dim>Generated {_esc(state['generated_at'])} from the evidence log. "
        "Every figure on this page is recomputed from that log on each request; "
        "nothing is stored. <a href='/api/state' style='color:var(--info)'>/api/state</a></p>"
    )
    return "".join(parts)


# --------------------------------------------------------------------------- #
# server
# --------------------------------------------------------------------------- #


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

        def log_message(self, *args: Any) -> None:  # silence request logging
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
    parser = argparse.ArgumentParser(description="Serve the read-only KEYRING dashboard")
    parser.add_argument("--evidence", default="evidence/raw")
    parser.add_argument("--strategy", default="config/strategy.yaml")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    serve(args.evidence, host=args.host, port=args.port, strategy_path=args.strategy)


if __name__ == "__main__":
    main()
