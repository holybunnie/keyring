"""Part VI - the permission trace.

Law 6: no badge without the evidence that produced it. Every classification
expands into a chain of observations that produced it, and every line names
one or more records in the append-only evidence log.

The trace deliberately distinguishes historical probes, whose planning fields
did not exist yet, from new static or model-planned probes. Historical records
are never rewritten to make the new schema appear retroactive.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from .authority import CAPABILITY_PREFIX, derive, is_write_tool_name
from .evidence import EvidenceLog
from .models import EvidenceRecord
from .provenance import qualified_label


def _all_records(evidence_dir: str | Path) -> list[tuple[str, EvidenceRecord]]:
    out: list[tuple[str, EvidenceRecord]] = []
    for path in sorted(Path(evidence_dir).glob("*.jsonl")):
        for record in EvidenceLog(path).records(verify=True):
            out.append((path.name, record))
    return out


def _ref(filename: str, sequence: int) -> str:
    return f"{filename}#{sequence}"


def _step(
    name: str,
    value: str,
    label: str,
    sources: Iterable[tuple[str, int]] | None = None,
) -> dict[str, Any]:
    refs = [_ref(filename, sequence) for filename, sequence in (sources or [])]
    return {
        "step": name,
        "value": value,
        "label": label,
        "evidence": ", ".join(refs) if refs else "—",
        "evidence_records": refs,
    }


def _tools_list(record: EvidenceRecord) -> list[dict[str, Any]]:
    if not (record.operation or "").startswith("tools/list"):
        return []
    try:
        body = json.loads(record.raw_response or "{}")
    except ValueError:
        return []
    tools = body.get("result", {}).get("tools", [])
    return [tool for tool in tools if isinstance(tool, dict)]


def _product_for_capability(capability: str) -> str | None:
    return next(
        (prefix for name, prefix in CAPABILITY_PREFIX.items() if name == capability),
        None,
    )


def _scope_key(record: EvidenceRecord) -> str:
    return record.granted_scope or "<scope not recorded>"


def trace(evidence_dir: str | Path = "evidence/raw") -> dict[str, Any]:
    """Build the proof chain behind every capability classification."""
    records = _all_records(evidence_dir)
    authority = derive(evidence_dir)
    record_by_ref = {
        (filename, record.sequence): record for filename, record in records
    }

    def label_for_refs(
        refs: Iterable[tuple[str, int]], fallback: str = "OBSERVED · harness"
    ) -> str:
        first = next(iter(refs), None)
        if first is None:
            return fallback
        source = record_by_ref.get(first)
        return qualified_label(source) if source is not None else fallback

    # Retain both the complete discovery references and the write names. This
    # lets a trace prove absence under the account-only grant as well as the
    # presence of writes under the trade grant.
    discovery_records: list[tuple[str, EvidenceRecord]] = [
        (filename, record) for filename, record in records if _tools_list(record)
    ]
    discovery_by_product: dict[str, list[str]] = {}
    discovery_refs_by_scope: dict[str, list[tuple[str, int]]] = {}
    for filename, record in discovery_records:
        scope_key = _scope_key(record)
        discovery_refs_by_scope.setdefault(scope_key, []).append((filename, record.sequence))
        for tool in _tools_list(record):
            name = str(tool.get("name", ""))
            if not is_write_tool_name(name):
                continue
            product_key = name.split(".", 1)[0]
            discovery_by_product.setdefault(product_key, []).append(name)

    # A scope-bearing discovery or initialize record is the source for the
    # grant line. The latest one is the scope used by the authority replay.
    scope_records = [
        (filename, record)
        for filename, record in records
        if record.granted_scope and record.operation in {"initialize", "tools/list"}
    ]
    if not scope_records:
        scope_records = [
            (filename, record) for filename, record in records if record.granted_scope
        ]
    latest_scope_record = scope_records[-1] if scope_records else None

    traces: dict[str, dict[str, Any]] = {}
    for capability, row in authority["capabilities"].items():
        steps: list[dict[str, Any]] = []
        product: str | None = _product_for_capability(capability)
        scope: str | None = row["scope_granted"] or (
            latest_scope_record[1].granted_scope if latest_scope_record else None
        )
        scope_sources = discovery_refs_by_scope.get(scope or "", [])
        if not scope_sources and latest_scope_record:
            scope_sources = [(latest_scope_record[0], latest_scope_record[1].sequence)]

        write_names = sorted(set(discovery_by_product.get(product or "", [])))
        surface_sources = [
            ref
            for ref in discovery_records
            if ref[1].granted_scope == scope
            or (scope is None and ref[1].granted_scope is None)
        ]
        surface_refs = [(filename, record.sequence) for filename, record in surface_sources]
        if not surface_refs and latest_scope_record:
            surface_refs = [(latest_scope_record[0], latest_scope_record[1].sequence)]
        if write_names:
            steps.append(
                _step(
                    "tool surface",
                    f"{len(write_names)} write tool(s) advertised: {', '.join(write_names)}",
                    qualified_label(surface_sources[0][1]) if surface_sources else "OBSERVED · harness",
                    surface_refs,
                )
            )
        else:
            steps.append(
                _step(
                    "tool surface",
                    "no write tool advertised under this grant",
                    qualified_label(surface_sources[0][1]) if surface_sources else "OBSERVED · harness",
                    surface_refs,
                )
            )

        if scope:
            steps.append(
                _step(
                    "grant",
                    scope,
                    label_for_refs(scope_sources),
                    scope_sources,
                )
            )

        # The delta is an evidence-backed comparison, not an inferred count.
        # Keep it as its own line because it is often the most useful answer to
        # what changed when trade was granted.
        account_scope = next(
            (name for name in discovery_refs_by_scope if name == "mcp:account:read"),
            None,
        )
        delta_sources = list(discovery_refs_by_scope.get(account_scope or "", []))
        delta_sources.extend(scope_sources)
        if account_scope and scope and account_scope != scope:
            steps.append(
                _step(
                    "discovery delta",
                    f"account-only versus selected grant; {len(write_names)} write tool(s) "
                    "in selected surface",
                    label_for_refs(scope_sources),
                    delta_sources,
                )
            )

        # Use the latest probe for a capability. A previous attempt can be
        # retained for audit history but must not shadow the current result.
        probe_candidates = [
            (filename, record)
            for filename, record in records
            if record.record_type == "capability_probe" and record.capability == capability
        ]
        probe_record = probe_candidates[-1] if probe_candidates else None
        if probe_record:
            filename, record = probe_record
            control_candidates = [
                (f, r)
                for f, r in records
                if r.record_type == "positive_control" and r.run_id == record.run_id
            ]
            if control_candidates:
                control_filename, control = control_candidates[-1]
                steps.append(
                    _step(
                        "positive control",
                        f"{control.operation or 'positive read'} passed at {control.occurred_at:%H:%M:%S}",
                        qualified_label(control),
                        [(control_filename, control.sequence)],
                    )
                )

            planned_by = record.planned_by or "not recorded (historical probe)"
            expected_filter = "not recorded"
            if record.model_proposal:
                expected_filter = str(
                    record.model_proposal.get("expected_filter", expected_filter)
                )
            justification = (
                record.probe_justification
                or record.metadata.get("probe_design")
                or "not recorded"
            )
            steps.append(
                _step(
                    "probe plan",
                    f"planned_by {planned_by}; expected {expected_filter}; "
                    f"justification: {justification}",
                    qualified_label(record),
                    [(filename, record.sequence)],
                )
            )
            steps.append(
                _step(
                    "probe",
                    f"{record.operation or 'probe'} invoked; final classification "
                    f"{row['classification']}",
                    qualified_label(record),
                    [(filename, record.sequence)],
                )
            )
            steps.append(
                _step(
                    "response",
                    f"{row['error_code'] or record.error_code or 'no Binance code'}: "
                    f"{record.raw_response or record.outcome or 'no response'}",
                    qualified_label(record),
                    [(filename, record.sequence)],
                )
            )
            if record.model_interpretation:
                steps.append(
                    _step(
                        "model interpretation",
                        json.dumps(record.model_interpretation, sort_keys=True, default=str),
                        qualified_label(record),
                        [(filename, record.sequence)],
                    )
                )
            before = record.state_before
            after = record.state_after
            if before and after:
                identical = before.digest == after.digest
                steps.append(
                    _step(
                        "financial state",
                        f"pre {before.digest[:12] if before.digest else '—'} / "
                        f"post {after.digest[:12] if after.digest else '—'} — "
                        f"{'IDENTICAL' if identical else 'CHANGED'} "
                        f"({len(before.components or {})} components, "
                        f"complete={before.complete() and after.complete()})",
                        qualified_label(record),
                        [(filename, record.sequence)],
                    )
                )
            steps.append(
                _step(
                    "classification",
                    row["classification"],
                    qualified_label(record, "OBSERVED" if row["classification"] != "INCONCLUSIVE" else "INCONCLUSIVE"),
                    [(filename, record.sequence)],
                )
            )
        else:
            classification_sources = surface_refs or scope_sources
            steps.append(
                _step(
                    "probe",
                    "not probed",
                    qualified_label(
                        surface_sources[0][1],
                        "INCONCLUSIVE" if row["classification"] == "INCONCLUSIVE" else "OBSERVED",
                    ) if surface_sources else ("INCONCLUSIVE" if row["classification"] == "INCONCLUSIVE" else "OBSERVED · harness"),
                    classification_sources,
                )
            )
            steps.append(
                _step(
                    "classification",
                    row["classification"],
                    qualified_label(
                        surface_sources[0][1],
                        "OBSERVED" if row["classification"] == "DENIED" else "INCONCLUSIVE",
                    ) if surface_sources else ("OBSERVED · harness" if row["classification"] == "DENIED" else "INCONCLUSIVE"),
                    classification_sources,
                )
            )

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
                f"  {step['step']:20} {step['value'][:70]:70} "
                f"{step['label']:19} {step['evidence']}"
            )
        for note in entry["notes"]:
            lines.append(f"  note: {note}")
        lines.append("")
    return "\n".join(lines)
