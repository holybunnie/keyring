from __future__ import annotations

import argparse
import html
import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .classifier import classify_log
from .config import load_probe_config, load_strategy_config
from .evidence import EvidenceLog
from .reach import layered_capital_view, least_privilege_diff
from .revocation import revocation_summary


def dashboard_state(evidence_path: str | Path, strategy_path: str | Path = "config/strategy.yaml") -> dict[str, Any]:
    log = EvidenceLog(evidence_path)
    records = log.records()
    strategy = load_strategy_config(strategy_path).model
    config = load_probe_config().model
    classifications = classify_log(log, [definition.id for definition in config.capabilities])
    diff = least_privilege_diff(strategy, classifications)
    verified = any(item.classification.value == "VERIFIED" for item in classifications)
    last_rate_limit = next((record for record in reversed(records) if record.http_status in {429, 418, 403}), None)
    used = sum(1 for record in records if record.record_type in {"probe", "capability_probe"})
    rate_limit_status = "HEALTHY"
    if last_rate_limit and last_rate_limit.http_status in {403, 418}:
        rate_limit_status = "HALTED"
    elif last_rate_limit and last_rate_limit.http_status == 429:
        rate_limit_status = "THROTTLED"
    return {
        "status": "MEASURED" if verified else "DEGRADED",
        "status_label": "OBSERVED",
        "records": len(records),
        "classifications": [item.model_dump(mode="json") for item in classifications],
        "strategy_diff": diff,
        "capital": layered_capital_view(records, classifications),
        "revocation": revocation_summary(records),
        "probe_budget": {
            "used": used,
            "max_per_run": config.budgets.max_probes_per_run,
            "label": "OBSERVED",
        },
        "rate_limit": {
            "status": rate_limit_status,
            "last_event": last_rate_limit.http_status if last_rate_limit else None,
            "label": "OBSERVED",
        },
        "disclaimer": "Effective authority is unavailable until a positive-control-backed probe proves it.",
        "disclaimer_label": "OBSERVED",
    }


def _page(state: dict[str, Any]) -> bytes:
    payload = html.escape(json.dumps(state, indent=2, ensure_ascii=False))
    rows = []
    for item in state["classifications"]:
        proof = html.escape(json.dumps(item["proof_chain"], indent=2, ensure_ascii=False))
        rows.append(
            "<tr>"
            f"<td>{html.escape(item['capability'])}</td>"
            f"<td><strong>{html.escape(item['classification'])}</strong></td>"
            f"<td>{html.escape(item['label'])}</td>"
            f"<td>{html.escape(item['reason'])}<details><summary>proof chain</summary><code>{proof}</code></details></td>"
            "</tr>"
        )
    if not rows:
        rows.append('<tr><td colspan="4">No capability probe classification is present in the evidence log.</td></tr>')
    capital_rows = []
    for name, item in state["capital"].items():
        value = html.escape(json.dumps(item["value"], ensure_ascii=False))
        capital_rows.append(
            f"<tr><td>{html.escape(name)}</td><td>{value}</td>"
            f"<td>{html.escape(item['label'])}</td><td>{html.escape(item['reason'])}</td></tr>"
        )
    revocation = state["revocation"]
    body = "".join(rows)
    capital_body = "".join(capital_rows)
    document = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>KEYRING</title><style>
body{{font:16px system-ui,sans-serif;max-width:1100px;margin:2rem auto;padding:0 1rem;background:#101217;color:#f4f5f7}}
article{{background:#191c24;border:1px solid #343946;border-radius:12px;padding:1rem;margin:1rem 0}}
table{{width:100%;border-collapse:collapse}}th,td{{text-align:left;border-bottom:1px solid #343946;padding:.6rem}}code{{white-space:pre-wrap;color:#b8c7ff}}
.label{{color:#f2c66d;font-size:.8rem;letter-spacing:.08em}} .status{{font-size:1.5rem}}
</style></head><body>
<h1>KEYRING</h1><p class="label">OBSERVED — local evidence-derived dashboard</p>
<article><div class="label">STATUS</div><div class="status">{html.escape(state['status'])}</div><p>{html.escape(state['disclaimer'])}</p></article>
<article><div class="label">CLASSIFICATIONS</div><table><thead><tr><th>Capability</th><th>Classification</th><th>Label</th><th>Proof-derived reason</th></tr></thead><tbody>{body}</tbody></table></article>
<article><div class="label">FINANCIAL REACH</div><table><thead><tr><th>Layer</th><th>Value</th><th>Label</th><th>Reason</th></tr></thead><tbody>{capital_body}</tbody></table></article>
<article><div class="label">PROBE BUDGET</div><p>{state['probe_budget']['used']} / {state['probe_budget']['max_per_run']} used this run — {state['probe_budget']['label']}</p>
<p>Rate-limit status: {html.escape(state['rate_limit']['status'])} — {state['rate_limit']['label']}</p></article>
<article><div class="label">REVOCATION</div><p>{html.escape(revocation['status'])} — {html.escape(revocation['label'])}; n={revocation['n']}</p><p>{html.escape(revocation['reason'])}</p></article>
<article><div class="label">RAW DASHBOARD STATE</div><code>{payload}</code></article>
</body></html>"""
    return document.encode("utf-8")


def create_server(
    evidence_path: str | Path,
    *,
    host: str = "127.0.0.1",
    port: int = 8080,
    strategy_path: str | Path = "config/strategy.yaml",
) -> ThreadingHTTPServer:
    state = dashboard_state(evidence_path, strategy_path)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/api/state":
                body = json.dumps(state, ensure_ascii=False).encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/json; charset=utf-8")
            elif self.path == "/":
                body = _page(state)
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/html; charset=utf-8")
            else:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:  # noqa: N802
            self.send_error(HTTPStatus.METHOD_NOT_ALLOWED)

        def log_message(self, format: str, *args: object) -> None:
            return

    return ThreadingHTTPServer((host, port), Handler)


def serve(evidence_path: str | Path, *, host: str = "127.0.0.1", port: int = 8080, strategy_path: str | Path = "config/strategy.yaml") -> None:
    server = create_server(evidence_path, host=host, port=port, strategy_path=strategy_path)
    print(f"KEYRING dashboard listening on {host}:{port}")
    try:
        server.serve_forever()
    finally:
        server.server_close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve the read-only KEYRING dashboard")
    parser.add_argument("--evidence", default="evidence/raw/0001-m0-preflight.jsonl")
    parser.add_argument("--strategy", default="config/strategy.yaml")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    serve(args.evidence, host=args.host, port=args.port, strategy_path=args.strategy)
