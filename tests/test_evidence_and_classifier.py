from pathlib import Path

from keyring.classifier import classify_log
from keyring.evidence import EvidenceLog
from keyring.labels import Classification
from keyring.models import EvidenceRecord, StateSnapshot


def snapshot() -> StateSnapshot:
    return StateSnapshot(
        captured=True,
        balances={"USDT": "0"},
        positions=[],
        open_orders=[],
        digest="same-state",
    )


def test_evidence_is_hash_chained_and_redacts_secrets(tmp_path: Path) -> None:
    log = EvidenceLog(tmp_path / "evidence.jsonl")
    log.append(
        EvidenceRecord(
            record_type="positive_control",
            run_id="run-1",
            label="OBSERVED",
            outcome="success",
            control_passed=True,
            request={"Authorization": "Bearer do-not-log-this"},
            raw_response='{"token":"do-not-log-this"}',
        )
    )
    log.append(
        EvidenceRecord(
            record_type="probe",
            run_id="run-1",
            label="OBSERVED",
            capability="spot",
            outcome="downstream_validation",
            error_code="-1013",
            state_before=snapshot(),
            state_after=snapshot(),
            state_unchanged=True,
        )
    )

    records = log.records()
    assert len(records) == 2
    assert records[0].request["Authorization"] == "[REDACTED]"
    assert "do-not-log-this" not in (tmp_path / "evidence.jsonl").read_text()
    assert records[1].prev_hash == records[0].record_hash


def test_classifier_derives_verified_from_control_and_state(tmp_path: Path) -> None:
    log = EvidenceLog(tmp_path / "evidence.jsonl")
    log.append(
        EvidenceRecord(
            record_type="positive_control",
            run_id="run-1",
            label="OBSERVED",
            outcome="success",
            control_passed=True,
        )
    )
    log.append(
        EvidenceRecord(
            record_type="probe",
            run_id="run-1",
            label="OBSERVED",
            capability="spot",
            outcome="downstream_validation",
            error_code="-1013",
            state_before=snapshot(),
            state_after=snapshot(),
            state_unchanged=True,
        )
    )

    result = classify_log(log)
    assert len(result) == 1
    assert result[0].classification == Classification.VERIFIED
    assert result[0].evidence_sequences == [1, 2]
    assert len(result[0].proof_chain) == 2


def test_classifier_refuses_a_probe_without_state_proof(tmp_path: Path) -> None:
    log = EvidenceLog(tmp_path / "evidence.jsonl")
    log.extend(
        [
            EvidenceRecord(
                record_type="positive_control",
                run_id="run-1",
                label="OBSERVED",
                outcome="success",
                control_passed=True,
            ),
            EvidenceRecord(
                record_type="probe",
                run_id="run-1",
                label="OBSERVED",
                capability="spot",
                outcome="downstream_validation",
                error_code="-1013",
                state_unchanged=False,
            ),
        ]
    )
    assert classify_log(log)[0].classification == Classification.INCONCLUSIVE
