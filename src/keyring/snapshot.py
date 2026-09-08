"""Complete financial-state capture, hashed and chained.

Law 3 requires that balances, positions and open orders are proved unchanged
before and after every probe, and that a probe which cannot prove it is
discarded rather than reported.

This module makes that claim checkable rather than asserted:

* Every component listed in `config/state_snapshot.yaml` is read before and
  after each probe. Components are READ tools only.
* The captured structure is canonicalised and hashed with SHA-256, so a
  before/after comparison is a single digest equality rather than a subjective
  diff.
* Snapshot digests are chained across the whole session, so the published claim
  becomes "nothing changed across the entire audit, here is the unbroken chain"
  rather than "this one probe changed nothing".

A component that fails to read is recorded in `missing`. If any *required*
component is missing, `StateSnapshot.complete()` is False and the caller must
discard the probe.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from .mcp import McpClient
from .models import StateSnapshot

DEFAULT_CONFIG = Path("config/state_snapshot.yaml")

# The three legs of the Law 3 proof. A snapshot missing any of these cannot
# support a zero-state-change claim.
REQUIRED_LEGS = ("balances", "positions", "open_orders")


def canonical(value: Any) -> str:
    """Stable JSON for hashing: sorted keys, no insignificant whitespace."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def digest_of(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class SnapshotComponent:
    id: str
    tool: str
    arguments: dict[str, Any]
    satisfies: str
    required: bool


def load_components(path: str | Path = DEFAULT_CONFIG) -> tuple[list[SnapshotComponent], str]:
    """Load the snapshot definition and its checksum."""
    path = Path(path)
    raw = path.read_bytes()
    checksum = hashlib.sha256(raw).hexdigest()
    document = yaml.safe_load(raw.decode("utf-8"))
    components = [
        SnapshotComponent(
            id=entry["id"],
            tool=entry["tool"],
            arguments=entry.get("arguments") or {},
            satisfies=entry["satisfies"],
            required=bool(entry.get("required", False)),
        )
        for entry in document["components"]
    ]
    return components, checksum


@dataclass
class SnapshotChain:
    """An ordered chain of state digests across one audit session."""

    entries: list[dict[str, Any]] = field(default_factory=list)

    def add(self, label: str, snapshot: StateSnapshot) -> dict[str, Any]:
        previous = self.entries[-1]["chain_hash"] if self.entries else None
        chain_hash = hashlib.sha256(
            f"{previous or ''}|{snapshot.digest}".encode("utf-8")
        ).hexdigest()
        entry = {
            "index": len(self.entries),
            "label": label,
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "state_digest": snapshot.digest,
            "prev_chain_hash": previous,
            "chain_hash": chain_hash,
            "complete": snapshot.complete(),
            "missing": list(snapshot.missing or []),
        }
        self.entries.append(entry)
        return entry

    def unbroken(self) -> bool:
        """True when every link recomputes and every snapshot was complete."""
        previous = None
        for entry in self.entries:
            expected = hashlib.sha256(
                f"{previous or ''}|{entry['state_digest']}".encode("utf-8")
            ).hexdigest()
            if expected != entry["chain_hash"] or not entry["complete"]:
                return False
            previous = entry["chain_hash"]
        return True

    def all_identical(self) -> bool:
        """True when every snapshot in the session hashed to the same state."""
        digests = {entry["state_digest"] for entry in self.entries}
        return len(digests) <= 1

    def report(self) -> dict[str, Any]:
        return {
            "snapshots": len(self.entries),
            "distinct_states": len({e["state_digest"] for e in self.entries}),
            "chain_unbroken": self.unbroken(),
            "state_identical_throughout": self.all_identical(),
            "entries": self.entries,
        }


def capture(
    client: McpClient,
    components: list[SnapshotComponent],
    *,
    config_sha256: str | None = None,
) -> tuple[StateSnapshot, list[Any]]:
    """Read every snapshot component and hash the result.

    Returns the snapshot and the raw ToolResults, so the caller can write the
    verbatim responses to the evidence log.
    """
    captured: dict[str, Any] = {}
    missing: list[str] = []
    raw_results = []
    legs: dict[str, dict[str, Any]] = {leg: {} for leg in REQUIRED_LEGS}

    for component in components:
        try:
            result = client.call_tool(component.tool, component.arguments)
            raw_results.append(result)
            if result.http_status != 200 or result.is_error:
                if component.required:
                    missing.append(component.id)
                captured[component.id] = {"unavailable": True, "http_status": result.http_status}
                continue
            captured[component.id] = result.payload
            if component.satisfies in legs:
                legs[component.satisfies][component.id] = result.payload
        except Exception as error:  # noqa: BLE001 - recorded, never silently dropped
            if component.required:
                missing.append(component.id)
            captured[component.id] = {"unavailable": True, "error": str(error)}

    for leg in REQUIRED_LEGS:
        if not legs[leg]:
            marker = f"<no {leg} component captured>"
            if marker not in missing:
                missing.append(marker)

    snapshot = StateSnapshot(
        captured=True,
        balances=legs["balances"] or None,
        positions=legs["positions"] or None,
        open_orders=legs["open_orders"] or None,
        components=captured,
        missing=missing or None,
        digest=digest_of(captured),
    )
    if config_sha256:
        snapshot = snapshot.model_copy(update={})
    return snapshot, raw_results


def compare(before: StateSnapshot, after: StateSnapshot) -> dict[str, Any]:
    """Compare two snapshots. Identical digests are the only passing result."""
    identical = (
        before.digest is not None
        and before.digest == after.digest
        and before.complete()
        and after.complete()
    )
    changed = []
    if not identical and before.components and after.components:
        for key in sorted(set(before.components) | set(after.components)):
            if before.components.get(key) != after.components.get(key):
                changed.append(key)
    return {
        "pre_probe_digest": before.digest,
        "post_probe_digest": after.digest,
        "identical": identical,
        "before_complete": before.complete(),
        "after_complete": after.complete(),
        "changed_components": changed,
        "verdict": "IDENTICAL" if identical else "STATE PROOF FAILED",
    }
