from datetime import datetime, timedelta, timezone

from keyring.labels import Classification, GateOutcome
from keyring.models import ClassificationResult, EvidenceRecord
from keyring.reach import layered_capital_view
from keyring.revocation import revocation_summary


def test_layered_capital_requires_an_explicit_state_link() -> None:
    records = [
        EvidenceRecord(
            record_type="account_snapshot",
            run_id="run-1",
            label="OBSERVED",
            response={"balances": {"USDT": "386.20"}},
        ),
        EvidenceRecord(
            record_type="probe",
            run_id="run-1",
            label="OBSERVED",
            capability="spot",
            gate=GateOutcome.CLIENT_GATED,
            outcome="downstream_validation",
            error_code="-1013",
            metadata={"capital_state_linked": True},
        ),
    ]
    classifications = [
        ClassificationResult(capability="spot", classification=Classification.VERIFIED, reason="state proof")
    ]
    view = layered_capital_view(records, classifications)
    assert view["capital_visible"]["value"] == {"USDT": "386.20"}
    assert view["capital_reachable_by_trading"]["label"] == "OBSERVED"
    assert view["autonomous_capital_at_risk"]["value"] == 0
    assert view["immediate_exit_cost"]["label"] == "INCONCLUSIVE"


def test_revocation_reports_sample_size_honestly() -> None:
    start = datetime(2026, 9, 6, 12, 0, tzinfo=timezone.utc)
    records = [
        EvidenceRecord(
            record_type="revocation_check",
            run_id="run-1",
            label="OBSERVED",
            occurred_at=start,
            outcome="access_permitted",
            metadata={"trial_id": "trial-1"},
        ),
        EvidenceRecord(
            record_type="revocation_check",
            run_id="run-1",
            label="OBSERVED",
            occurred_at=start + timedelta(seconds=1.2),
            outcome="access_denied",
            metadata={"trial_id": "trial-1"},
        ),
    ]
    summary = revocation_summary(records)
    assert summary["status"] == "VERIFIED"
    assert summary["n"] == 1
    assert summary["convergence_seconds"] == 1.2


def test_revocation_uses_last_permitted_baseline() -> None:
    start = datetime(2026, 9, 6, 12, 0, tzinfo=timezone.utc)
    records = [
        EvidenceRecord(
            record_type="revocation_check", run_id="run-2", label="OBSERVED",
            occurred_at=start, outcome="access_permitted",
            metadata={"trial_id": "trial-2"},
        ),
        EvidenceRecord(
            record_type="revocation_check", run_id="run-2", label="OBSERVED",
            occurred_at=start + timedelta(seconds=30), outcome="access_permitted",
            metadata={"trial_id": "trial-2"},
        ),
        EvidenceRecord(
            record_type="revocation_check", run_id="run-2", label="OBSERVED",
            occurred_at=start + timedelta(seconds=31.5), outcome="access_denied",
            metadata={"trial_id": "trial-2"},
        ),
    ]
    summary = revocation_summary(records)
    assert summary["convergence_seconds"] == 1.5
