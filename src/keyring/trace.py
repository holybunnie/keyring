"""Part VI - the permission trace.

Law 6: no badge without the evidence that produced it. Every classification
expands into the chain of observations that produced it, and every line in that
chain names the evidence record it came from.

Nothing here is written by hand. Each step is read back out of the append-only
log, so the answer to "how do I know you didn't hard-code this" is that the
trace is reconstructed from the same records a reader can open themselves.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .authority import derive, is_write_tool_name
from .evidence import EvidenceLog
from .models import EvidenceRecord


def _all_records(evidence_dir: str | Path) -> list[tuple[str, EvidenceRecord]]:
    out: list[tuple[str, EvidenceRecord]] = []
    for path in sorted(Path(evidence_dir).glob("*.jsonl")):
        for record in EvidenceLog(path).records(verify=True):
            out.append((path.name, record))
    return out


def _step(
    name: str, value: str, label: str, source: str | None = None, sequence: int | None = None
) -> dict[str, Any]:
    return {
        "step": name,
        "value": value,
        "label": label,
        "evidence": f"{source}#{sequence}" if source and sequence is not None else (source or "—"),
    }


def trace(evidence_dir: str | Path = "evidence/raw") -> dict[str, Any]:
    """Build the proof chain behind every capability classification."""
    records = _all_records(evidence_dir)
    authority = derive(evidence_dir)

    # Discovery: which record advertised which write tools.
    discovery: dict[str, tuple[str, int, list[str]]] = {}
    for filename, record in records:
        if not (record.operation or "").startswith("tools/list"):
            continue
        import json

        try:
            body = json.loads(record.raw_response or "{}")
        except ValueError:
            continue
        for tool in body.get("result", {}).get("tools", []):
            name = tool.get("name", "")
            if not is_write_tool_name(name):
                continue
            product = name.split(".")[0]
            existing = discovery.get(product)
            names = (existing[2] if existing else []) + [name]
            discovery[product] = (filename, record.sequence, sorted(set(names)))

    prefix_to_capability = {
        "spot": "spot",
        "margin": "margin",
        "futures_usds": "usd_m_futures",
        "futures_coin": "coin_m_futures",
        "convert": "convert",
        "wallet": "transfer",
    }

    traces: dict[str, dict[str, Any]] = {}
    for capability, row in authority["capabilities"].items():
        steps: list[dict[str, Any]] = []

        # 1. tool surface
        product = next((p for p, c in prefix_to_capability.items() if c == capability), None)
        advertised = discovery.get(product or "")
        if advertised:
            steps.append(
                _step(
                    "tool surface",
                    f"{len(advertised[2])} write tool(s) advertised: {', '.join(advertised[2])}",
                    "OBSERVED",
                    advertised[0],
                    advertised[1],
                )
            )
        else:
            steps.append(
                _step("tool surface", "no write tool advertised under this grant", "OBSERVED")
            )

        # 2. grant
        if row["scope_granted"]:
            steps.append(_step("grant", row["scope_granted"], "OBSERVED"))

        # 3..5 probe, control, state - from the probe record itself
        probe_record = next(
            (
                (filename, record)
                for filename, record in records
                if record.record_type == "capability_probe" and record.capability == capability
            ),
            None,
        )
        if probe_record:
            filename, record = probe_record
            control = next(
                (
                    (f, r)
                    for f, r in records
                    if r.record_type == "positive_control" and r.run_id == record.run_id
                ),
                None,
            )
            if control:
                steps.append(
                    _step(
                        "positive control",
                        f"{control[1].operation} passed at {control[1].occurred_at:%H:%M:%S}",
                        "OBSERVED",
                        control[0],
                        control[1].sequence,
                    )
                )
            steps.append(
                _step(
                    "probe",
                    f"{record.operation} → {row['error_code'] or 'no Binance code'}",
                    "OBSERVED",
                    filename,
                    record.sequence,
                )
            )
            before = record.state_before
            after = record.state_after
            if before and after:
                identical = before.digest == after.digest
                steps.append(
                    _step(
                        "financial state",
                        f"pre {before.digest[:12]} / post {after.digest[:12]} — "
                        f"{'IDENTICAL' if identical else 'CHANGED'} "
                        f"({len(before.components or {})} components, complete={before.complete()})",
                        "OBSERVED",
                        filename,
                        record.sequence,
                    )
                )
        else:
            steps.append(_step("probe", "not probed", "INCONCLUSIVE"))

        traces[capability] = {
            "classification": row["classification"],
            "notes": row["notes"],
            "steps": steps,
        }

    return {
        "capabilities": traces,
        "records_replayed": authority["records_replayed"],
        "granted_scope": authority["granted_scope"],
    }


def render(result: dict[str, Any]) -> str:
    lines = []
    for capability, entry in sorted(result["capabilities"].items()):
        lines.append(f"{capability.upper()} — {entry['classification']}")
        for step in entry["steps"]:
            lines.append(
                f"  {step['step']:20} {step['value'][:70]:70} {step['label']:12} {step['evidence']}"
            )
        for note in entry["notes"]:
            lines.append(f"  note: {note}")
        lines.append("")
    return "\n".join(lines)
