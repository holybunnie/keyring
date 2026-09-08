from __future__ import annotations

from datetime import datetime
from typing import Any

from .models import EvidenceRecord


def _timestamp(record: EvidenceRecord) -> datetime:
    return record.occurred_at


def revocation_summary(records: list[EvidenceRecord]) -> dict[str, Any]:
    """Summarize only manually recorded revocation checks; never trigger revocation."""
    checks = [record for record in records if record.record_type == "revocation_check"]
    trials: dict[str, list[EvidenceRecord]] = {}
    for record in checks:
        trial_id = str(record.metadata.get("trial_id", record.run_id))
        trials.setdefault(trial_id, []).append(record)

    convergences: list[float] = []
    for trial_records in trials.values():
        permitted = [record for record in trial_records if record.outcome == "access_permitted"]
        denied = [record for record in trial_records if record.outcome == "access_denied"]
        if permitted and denied:
            first_denied = min(denied, key=_timestamp)
            # The poller records the access transition, but the web UI click
            # is not necessarily timestamped by the client. Use the last
            # permitted response before the first denied response so a long
            # pre-disconnect baseline is not misreported as revocation time.
            last_permitted = max(
                (
                    record
                    for record in permitted
                    if _timestamp(record) <= _timestamp(first_denied)
                ),
                key=_timestamp,
                default=None,
            )
            if last_permitted is None:
                continue
            delta = (first_denied.occurred_at - last_permitted.occurred_at).total_seconds()
            if delta >= 0:
                convergences.append(delta)

    if not convergences:
        return {
            "status": "INCONCLUSIVE",
            "label": "INCONCLUSIVE",
            "n": 0,
            "convergence_seconds": None,
            "reason": "no permitted-to-denied revocation trial is present",
        }
    return {
        "status": "VERIFIED",
        "label": "OBSERVED · operator",
        "capture_origin": "operator",
        "n": len(convergences),
        "convergence_seconds": convergences[0] if len(convergences) == 1 else convergences,
        "reason": (
            "manually recorded revocation trial: known-permitted reads were followed by a "
            "denied read; interval is measured from the last permitted response to the "
            "first denied response, not from the web UI click"
        ),
    }
