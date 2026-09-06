from pathlib import Path

import pytest

from keyring.classifier import classify_log
from keyring.evidence import EvidenceLog
from keyring.labels import Classification
from keyring.models import ProbeDefinition, StateSnapshot
from keyring.safety import AdapterResponse, ControlFailed, ProbeBudget, RateLimitPolicy, SafeProbeRunner, SafetyHalt


def snapshot() -> StateSnapshot:
    return StateSnapshot(captured=True, balances={}, positions=[], open_orders=[], digest="stable")


def definition() -> ProbeDefinition:
    return ProbeDefinition(
        id="spot",
        scope="trade",
        product="spot",
        operation="order_validation",
        probe_policy="non_executing_only",
        symbol_source="exchangeInfo",
        threshold_source="exchangeInfo.filters.MIN_NOTIONAL",
    )


class FakeAdapter:
    def __init__(self, responses: list[AdapterResponse], control: AdapterResponse | None = None):
        self.responses = iter(responses)
        self.control = control or AdapterResponse(status=200, outcome="success")
        self.probe_calls = 0

    def positive_control(self) -> AdapterResponse:
        return self.control

    def before_state(self) -> StateSnapshot:
        return snapshot()

    def probe(self, _definition: ProbeDefinition) -> AdapterResponse:
        self.probe_calls += 1
        return next(self.responses)

    def after_state(self) -> StateSnapshot:
        return snapshot()


def test_runner_requires_positive_control(tmp_path: Path) -> None:
    adapter = FakeAdapter(
        [AdapterResponse(status=200, outcome="downstream_validation", error_code="-1013")],
        control=AdapterResponse(status=403, outcome="failure"),
    )
    runner = SafeProbeRunner(log=EvidenceLog(tmp_path / "evidence.jsonl"), budget=ProbeBudget(1, 1))
    with pytest.raises(ControlFailed):
        runner.run_batch("run-1", adapter, [definition()])
    assert adapter.probe_calls == 0


def test_runner_retries_429_and_classifies_validation(tmp_path: Path) -> None:
    sleeps: list[float] = []
    adapter = FakeAdapter(
        [
            AdapterResponse(status=429, outcome="rate_limited", headers={"Retry-After": "3"}),
            AdapterResponse(status=200, outcome="downstream_validation", error_code="-1013"),
        ]
    )
    log = EvidenceLog(tmp_path / "evidence.jsonl")
    runner = SafeProbeRunner(log=log, budget=ProbeBudget(1, 1), sleeper=sleeps.append)
    runner.run_batch("run-1", adapter, [definition()])

    assert sleeps == [3.0]
    assert adapter.probe_calls == 2
    assert classify_log(log)[0].classification == Classification.VERIFIED


def test_rate_policy_halts_418_and_403() -> None:
    policy = RateLimitPolicy()
    assert policy.inspect(418).action == "HALT"
    assert policy.inspect(403).action == "HALT"
    assert policy.inspect(500).action == "INCONCLUSIVE"
    assert policy.inspect(429, {"Retry-After": "120"}).delay_seconds == 120


def test_halt_response_is_written_before_runner_stops(tmp_path: Path) -> None:
    adapter = FakeAdapter([AdapterResponse(status=418, outcome="banned", raw_response='{"code":418}')])
    log = EvidenceLog(tmp_path / "evidence.jsonl")
    runner = SafeProbeRunner(log=log, budget=ProbeBudget(1, 1))
    with pytest.raises(SafetyHalt):
        runner.run_batch("run-1", adapter, [definition()])
    records = log.records()
    assert records[-1].record_type == "probe"
    assert records[-1].http_status == 418
    assert records[-1].state_unchanged is True
