from __future__ import annotations

import email.utils
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Callable, Iterable, Literal, Protocol

from .evidence import EvidenceLog
from .labels import GateOutcome
from .models import EvidenceRecord, ProbeDefinition, StateSnapshot

if TYPE_CHECKING:
    from .interpreter import ResponseInterpreter


class ProbeSafetyError(RuntimeError):
    pass


class ProbeBudgetExceeded(ProbeSafetyError):
    pass


class ControlFailed(ProbeSafetyError):
    pass


class SafetyHalt(ProbeSafetyError):
    pass


@dataclass
class ProbeBudget:
    max_per_run: int
    max_per_minute: int
    clock: Callable[[], float] = time.monotonic
    _run_count: int = 0
    _capabilities: set[str] = field(default_factory=set)
    _timestamps: list[float] = field(default_factory=list)

    def reserve(self, capability: str) -> None:
        now = self.clock()
        self._timestamps = [stamp for stamp in self._timestamps if now - stamp < 60]
        if capability in self._capabilities:
            raise ProbeBudgetExceeded(f"one probe per capability already reserved: {capability}")
        if self._run_count >= self.max_per_run:
            raise ProbeBudgetExceeded("per-run probe budget exhausted")
        if len(self._timestamps) >= self.max_per_minute:
            raise ProbeBudgetExceeded("per-minute probe budget exhausted")
        self._capabilities.add(capability)
        self._run_count += 1
        self._timestamps.append(now)


@dataclass(frozen=True)
class RateLimitDecision:
    action: str
    delay_seconds: float = 0
    reason: str = ""


class RateLimitPolicy:
    def __init__(
        self,
        *,
        retry_after_cap_seconds: float = 60,
        backoff_base_seconds: float = 1,
        backoff_max_seconds: float = 32,
        max_retries: int = 3,
    ):
        self.retry_after_cap_seconds = retry_after_cap_seconds
        self.backoff_base_seconds = backoff_base_seconds
        self.backoff_max_seconds = backoff_max_seconds
        self.max_retries = max_retries

    def _retry_after(self, headers: dict[str, str], now: datetime | None = None) -> float | None:
        value = headers.get("Retry-After") or headers.get("retry-after")
        if not value:
            return None
        try:
            # A server-provided Retry-After value takes precedence over the
            # local cap; the cap applies only to locally generated backoff.
            return max(0.0, float(value))
        except ValueError:
            try:
                parsed = email.utils.parsedate_to_datetime(value)
                reference = now or datetime.now(timezone.utc)
                return max(0.0, (parsed - reference).total_seconds())
            except (TypeError, ValueError, OverflowError):
                return None

    def inspect(self, status: int, headers: dict[str, str] | None = None, attempt: int = 0) -> RateLimitDecision:
        headers = headers or {}
        if status == 429:
            retry_after = self._retry_after(headers)
            backoff = min(self.backoff_base_seconds * (2**attempt), self.backoff_max_seconds)
            delay = retry_after if retry_after is not None else backoff
            return RateLimitDecision("RETRY", delay, "429 rate limit; honour Retry-After or exponential backoff")
        if status == 418:
            return RateLimitDecision("HALT", 0, "418 ban response; no retry")
        if status == 403:
            return RateLimitDecision("HALT", 0, "403 response; investigate before resuming")
        if status >= 500:
            return RateLimitDecision("INCONCLUSIVE", 0, "5xx response; no aggressive retry")
        return RateLimitDecision("CONTINUE")


class ProbeAdapter(Protocol):
    def positive_control(self) -> "AdapterResponse": ...

    def before_state(self) -> StateSnapshot: ...

    def probe(self, definition: ProbeDefinition) -> "AdapterResponse": ...

    def after_state(self) -> StateSnapshot: ...


@dataclass(frozen=True)
class AdapterResponse:
    status: int | None
    outcome: str
    error_code: str | None = None
    raw_response: str | None = None
    response: object = None
    headers: dict[str, str] = field(default_factory=dict)
    gate: GateOutcome | None = None
    advertised: bool | None = None
    granted_scope: str | None = None
    planned_by: Literal["model", "static"] = "static"
    probe_justification: str | None = None
    model_proposal: dict[str, Any] | None = None


class SafeProbeRunner:
    """Runs only after a passing control and retains state proof for every probe."""

    def __init__(
        self,
        *,
        log: EvidenceLog,
        budget: ProbeBudget,
        rate_limits: RateLimitPolicy | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        interpreter: "ResponseInterpreter | None" = None,
    ):
        self.log = log
        self.budget = budget
        self.rate_limits = rate_limits or RateLimitPolicy()
        self.sleeper = sleeper
        self.interpreter = interpreter

    def run_batch(self, run_id: str, adapter: ProbeAdapter, definitions: Iterable[ProbeDefinition], config_sha256: str | None = None) -> list[EvidenceRecord]:
        control_attempt = 0
        while True:
            control = adapter.positive_control()
            control_decision = self.rate_limits.inspect(control.status or 0, control.headers, control_attempt)
            control_passed = control.outcome == "success" and (control.status is None or 200 <= control.status < 300)
            if control_decision.action == "RETRY" and control_attempt < self.rate_limits.max_retries:
                self.log.append(
                    EvidenceRecord(
                        record_type="positive_control_attempt",
                        run_id=run_id,
                        label="OBSERVED",
                        operation="account_read",
                        response=control.response,
                        raw_response=control.raw_response,
                        http_status=control.status,
                        error_code=control.error_code,
                        outcome=control.outcome,
                        control_passed=False,
                        config_sha256=config_sha256,
                        metadata={"attempt": control_attempt, "rate_limit_action": control_decision.action},
                    )
                )
                remaining = control_decision.delay_seconds
                while remaining > 0:
                    delay = min(remaining, 60)
                    self.sleeper(delay)
                    remaining -= delay
                control_attempt += 1
                continue
            control_record = self.log.append(
                EvidenceRecord(
                    record_type="positive_control",
                    run_id=run_id,
                    label="OBSERVED",
                    operation="account_read",
                    response=control.response,
                    raw_response=control.raw_response,
                    http_status=control.status,
                    error_code=control.error_code,
                    outcome=control.outcome,
                    control_passed=control_passed,
                    config_sha256=config_sha256,
                    metadata={"attempt": control_attempt, "rate_limit_action": control_decision.action},
                )
            )
            if control_decision.action == "HALT":
                raise SafetyHalt(control_decision.reason)
            if control_decision.action == "INCONCLUSIVE" or control_record.control_passed is not True:
                raise ControlFailed("positive control failed; probe batch discarded")
            break

        appended: list[EvidenceRecord] = [control_record]
        for definition in definitions:
            if definition.probe_policy != "non_executing_only":
                raise ProbeSafetyError(f"unsupported probe policy: {definition.probe_policy}")
            self.budget.reserve(definition.id)
            response: AdapterResponse | None = None
            final_before: StateSnapshot | None = None
            final_after: StateSnapshot | None = None
            halt_reason: str | None = None
            attempt = 0
            while attempt <= self.rate_limits.max_retries:
                before = adapter.before_state()
                response = adapter.probe(definition)
                after = adapter.after_state()
                unchanged = before.complete() and after.complete() and before == after
                decision = self.rate_limits.inspect(response.status or 0, response.headers, attempt)
                if decision.action == "RETRY" and attempt < self.rate_limits.max_retries:
                    appended.append(
                        self.log.append(
                            EvidenceRecord(
                                record_type="probe_attempt",
                                run_id=run_id,
                                label="OBSERVED",
                                capability=definition.id,
                                operation=definition.operation,
                                response=response.response,
                                raw_response=response.raw_response,
                                http_status=response.status,
                                error_code=response.error_code,
                                outcome=response.outcome,
                                gate=response.gate,
                                advertised=response.advertised,
                                granted_scope=response.granted_scope,
                                state_before=before,
                                state_after=after,
                                state_unchanged=unchanged,
                                config_sha256=config_sha256,
                                planned_by=response.planned_by,
                                probe_justification=(
                                    response.probe_justification
                                    or f"static non-executing probe definition: {definition.id}"
                                ),
                                model_proposal=response.model_proposal,
                                metadata={"attempt": attempt, "rate_limit_action": decision.action},
                            )
                        )
                    )
                    remaining = decision.delay_seconds
                    while remaining > 0:
                        delay = min(remaining, 60)
                        self.sleeper(delay)
                        remaining -= delay
                    attempt += 1
                    continue
                final_before = before
                final_after = after
                if decision.action == "HALT":
                    halt_reason = decision.reason
                break
            assert response is not None and final_before is not None and final_after is not None
            state_unchanged = (
                final_before.complete()
                and final_after.complete()
                and final_before == final_after
            )
            model_interpretation = None
            if self.interpreter is not None and state_unchanged:
                interpretation = self.interpreter.interpret(
                    raw_response=response.raw_response or "",
                    error_code=response.error_code,
                    outcome=response.outcome,
                    context={
                        "capability": definition.id,
                        "tool": definition.operation,
                        "runner": "SafeProbeRunner",
                    },
                )
                if interpretation.model_assisted:
                    model_interpretation = interpretation.as_dict()
            appended.append(
                self.log.append(
                    EvidenceRecord(
                        record_type="probe",
                        run_id=run_id,
                        label="OBSERVED",
                        capability=definition.id,
                        operation=definition.operation,
                        response=response.response,
                        raw_response=response.raw_response,
                        http_status=response.status,
                        error_code=response.error_code,
                        outcome=response.outcome,
                        gate=response.gate,
                        advertised=response.advertised,
                        granted_scope=response.granted_scope,
                        state_before=final_before,
                        state_after=final_after,
                        state_unchanged=state_unchanged,
                        config_sha256=config_sha256,
                        planned_by=response.planned_by,
                        probe_justification=(
                            response.probe_justification
                            or f"static non-executing probe definition: {definition.id}"
                        ),
                        model_proposal=response.model_proposal,
                        model_interpretation=model_interpretation,
                        metadata={"attempt": attempt},
                    )
                )
            )
            if halt_reason is not None:
                raise SafetyHalt(halt_reason)
        return appended
