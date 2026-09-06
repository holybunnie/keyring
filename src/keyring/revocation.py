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
            first_permitted = min(permitted, key=_timestamp)
            first_denied = min(denied, key=_timestamp)
            delta = (first_denied.occurred_at - first_permitted.occurred_at).total_seconds()
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
        "label": "OBSERVED",
        "n": len(convergences),
        "convergence_seconds": convergences[0] if len(convergences) == 1 else convergences,
        "reason": "known-permitted reads were followed by denied reads after a recorded disconnect",
    }
