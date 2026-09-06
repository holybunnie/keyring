from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from .evidence import EvidenceLog
from .labels import Classification
from .models import ClassificationResult, EvidenceRecord


def _control_records(records: Iterable[EvidenceRecord]) -> dict[str, EvidenceRecord]:
    controls: dict[str, EvidenceRecord] = {}
    for record in records:
        if record.record_type == "positive_control":
            controls[record.run_id] = record
    return controls


def _proof(record: EvidenceRecord, control: EvidenceRecord | None) -> list[dict[str, object]]:
    chain: list[dict[str, object]] = []
    if control is not None:
        chain.append(
            {
                "sequence": control.sequence,
                "event": "positive_control",
                "label": control.label.value,
                "outcome": control.outcome,
            }
        )
    chain.append(
        {
            "sequence": record.sequence,
            "event": record.record_type,
            "label": record.label.value,
            "outcome": record.outcome,
            "error_code": record.error_code,
            "state_unchanged": record.state_unchanged,
        }
    )
    return chain


def classify_records(records: list[EvidenceRecord]) -> list[ClassificationResult]:
    controls = _control_records(records)
    grouped: dict[str, list[EvidenceRecord]] = defaultdict(list)
    for record in records:
        if record.record_type in {"probe", "capability_probe"} and record.capability:
            grouped[record.capability].append(record)

    results: list[ClassificationResult] = []
    for capability, candidates in grouped.items():
        record = candidates[-1]
        control = controls.get(record.run_id)
        evidence_sequences = [record.sequence]
        if control is not None:
            evidence_sequences.insert(0, control.sequence)

        if control is None or control.control_passed is not True:
            classification = Classification.INCONCLUSIVE
            reason = "positive control missing or failed"
        elif record.state_unchanged is not True:
            classification = Classification.INCONCLUSIVE
            reason = "before/after financial state was not proven unchanged"
        elif record.http_status in {403, 418} or (record.http_status is not None and record.http_status >= 500):
            classification = Classification.INCONCLUSIVE
            reason = "halt-class or server failure response"
        elif record.outcome == "downstream_validation" and record.error_code == "-1013":
            classification = Classification.VERIFIED
            reason = "probe reached downstream validation and state was unchanged"
        elif record.outcome == "authorization_denied" and record.error_code == "-2015":
            classification = Classification.DENIED
            reason = "authorization-class failure with a passing positive control"
        elif record.outcome == "advertised_only":
            classification = Classification.ADVERTISED_ONLY
            reason = "surface advertised the capability but the grant could not invoke it"
        else:
            classification = Classification.INCONCLUSIVE
            reason = "response did not match a supported classification rule"

        results.append(
            ClassificationResult(
                capability=capability,
                classification=classification,
                reason=reason,
                evidence_sequences=evidence_sequences,
                proof_chain=_proof(record, control),
            )
        )
    return results


def classify_log(log: EvidenceLog) -> list[ClassificationResult]:
    return classify_records(log.records())
