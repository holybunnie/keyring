"""Derive the effective authority map from the evidence log alone.

Nothing here is hand-entered. Every row is reconstructed by replaying the
append-only evidence records: what the gateway advertised, what scope was
granted, whether the positive control passed, what the probe returned, and
whether the state digests before and after were identical.

Running this against the logs must reproduce the published dashboard exactly.
That is the answer to "how do I know you didn't just type this in".
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .evidence import EvidenceLog
from .mcp import _binance_error_code
from .models import EvidenceRecord
from .prober import classify_error_code

# Which advertised tool names correspond to which capability. Derived from the
# OBSERVED tool surface naming pattern {product}.{operation}.
CAPABILITY_PREFIX = {
    "spot": "spot",
    "margin": "margin",
    "usd_m_futures": "futures_usds",
    "coin_m_futures": "futures_coin",
    "convert": "convert",
    "transfer": "wallet",
}

# A tool is state-changing when its OPERATION begins with one of these verbs.
#
# Matching on the operation rather than the whole name matters: `margin.queryMaxBorrow`
# and `wallet.queryUserUniversalTransferHistory` contain "Borrow" and "Transfer"
# but are both reads. OBSERVED: every write tool in the captured surface begins
# with new / cancel / delete / change.
WRITE_VERBS = ("new", "cancel", "delete", "change", "transfer", "borrow", "repay", "place", "accept")
READ_VERBS = ("query", "get", "list", "current", "all")


def is_write_tool_name(name: str) -> bool:
    operation = name.split(".")[-1]
    lowered = operation[0].lower() + operation[1:] if operation else ""
    if lowered.startswith(READ_VERBS):
        return False
    return lowered.startswith(WRITE_VERBS)


@dataclass
class CapabilityRow:
    capability: str
    advertised_write_tools: list[str] = field(default_factory=list)
    scope_granted: str | None = None
    probe_tool: str | None = None
    error_code: str | None = None
    outcome: str | None = None
    control_passed: bool | None = None
    state_unchanged: bool | None = None
    state_before: str | None = None
    state_after: str | None = None
    classification: str = "INCONCLUSIVE"
    notes: list[str] = field(default_factory=list)

    def resolve(self) -> None:
        """Apply Law 5. Order matters: state proof gates everything."""
        advertised = bool(self.advertised_write_tools)

        if self.probe_tool is None:
            if advertised:
                self.classification = "INCONCLUSIVE"
                self.notes.append("advertised but never probed")
            else:
                self.classification = "DENIED"
                self.notes.append("no write tool advertised under this grant")
            return

        if self.control_passed is False:
            self.classification = "INCONCLUSIVE"
            self.notes.append("positive control failed; discarded under Law 4")
            return

        if not self.state_unchanged:
            self.classification = "INCONCLUSIVE"
            self.notes.append("state proof failed; discarded under Law 3")
            return

        if (self.outcome or "").lower() == "advertised_only":
            self.classification = "ADVERTISED_ONLY"
            self.notes.append("surface advertised the capability but the grant could not invoke it")
            return

        self.classification = classify_error_code(self.error_code)
        if self.classification == "INCONCLUSIVE" and self.error_code:
            self.notes.append(f"error code {self.error_code} not in a known class")


def _load_records(paths: Iterable[str | Path]) -> list[EvidenceRecord]:
    records: list[EvidenceRecord] = []
    for path in paths:
        path = Path(path)
        if path.exists():
            records.extend(EvidenceLog(path).records(verify=True))
    return records


def derive(evidence_dir: str | Path = "evidence/raw") -> dict[str, Any]:
    """Rebuild the authority map from every evidence file in a directory."""
    paths = sorted(Path(evidence_dir).glob("*.jsonl"))
    records = _load_records(paths)

    advertised: dict[str, list[str]] = defaultdict(list)
    latest_scope: str | None = None

    for record in records:
        if record.operation and record.operation.startswith("tools/list") and record.raw_response:
            try:
                body = json.loads(record.raw_response)
            except ValueError:
                continue
            for tool in body.get("result", {}).get("tools", []):
                name = tool.get("name", "")
                if not is_write_tool_name(name):
                    continue
                for capability, prefix in CAPABILITY_PREFIX.items():
                    if name.startswith(prefix + ".") and name not in advertised[capability]:
                        advertised[capability].append(name)
            if record.granted_scope:
                latest_scope = record.granted_scope

    rows: dict[str, CapabilityRow] = {}
    for capability in CAPABILITY_PREFIX:
        rows[capability] = CapabilityRow(
            capability=capability,
            advertised_write_tools=sorted(advertised.get(capability, [])),
            scope_granted=latest_scope,
        )

    for record in records:
        if record.record_type != "capability_probe" or not record.capability:
            continue
        row = rows.setdefault(record.capability, CapabilityRow(capability=record.capability))
        row.probe_tool = record.operation
        # Re-extract from the raw response rather than trusting the stored
        # field: the extractor has been corrected since some records were
        # written, and the raw response is the evidence.
        row.error_code = _binance_error_code(record.raw_response or "") or record.error_code
        row.outcome = record.outcome
        row.control_passed = record.control_passed
        row.state_unchanged = record.state_unchanged
        row.state_before = record.state_before.digest if record.state_before else None
        row.state_after = record.state_after.digest if record.state_after else None
        if record.granted_scope:
            row.scope_granted = record.granted_scope

    for row in rows.values():
        row.resolve()

    digests = [
        record.state_before.digest
        for record in records
        if record.state_before and record.state_before.digest
    ] + [
        record.state_after.digest
        for record in records
        if record.state_after and record.state_after.digest
    ]

    return {
        "evidence_files": [str(p) for p in paths],
        "records_replayed": len(records),
        "granted_scope": latest_scope,
        "state_digests_seen": len(digests),
        "distinct_states": len(set(digests)),
        "state_identical_throughout": len(set(digests)) <= 1,
        "capabilities": {
            name: {
                "advertised_write_tools": row.advertised_write_tools,
                "scope_granted": row.scope_granted,
                "probe_tool": row.probe_tool,
                "error_code": row.error_code,
                "control_passed": row.control_passed,
                "state_unchanged": row.state_unchanged,
                "classification": row.classification,
                "notes": row.notes,
            }
            for name, row in sorted(rows.items())
        },
    }


def render(result: dict[str, Any]) -> str:
    """Human-readable authority map, for the terminal and the README."""
    lines = [
        "EFFECTIVE AUTHORITY MAP  (derived from evidence log only)",
        f"  records replayed        {result['records_replayed']}",
        f"  granted scope           {result['granted_scope']}",
        f"  state digests seen      {result['state_digests_seen']}",
        f"  distinct states         {result['distinct_states']}",
        f"  identical throughout    {result['state_identical_throughout']}",
        "",
    ]
    for name, row in result["capabilities"].items():
        lines.append(f"{name.upper()}")
        lines.append(f"  advertised write tools   {len(row['advertised_write_tools'])}")
        lines.append(f"  probe                    {row['probe_tool'] or 'not probed'}")
        lines.append(f"  error code               {row['error_code'] or '-'}")
        lines.append(f"  positive control         {row['control_passed']}")
        lines.append(f"  state unchanged          {row['state_unchanged']}")
        lines.append(f"  classification           {row['classification']}")
        for note in row["notes"]:
            lines.append(f"    note: {note}")
        lines.append("")
    return "\n".join(lines)
