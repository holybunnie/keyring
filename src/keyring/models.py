from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .labels import Classification, EvidenceLabel, GateOutcome


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class StateSnapshot(BaseModel):
    """The state needed to prove that a probe had no financial effect."""

    model_config = ConfigDict(extra="forbid")

    captured: bool = False
    balances: Any = None
    positions: Any = None
    open_orders: Any = None
    digest: str | None = None

    # Every component read that composed this snapshot, keyed by component id.
    components: Any = None
    # Component ids that were required but could not be captured. A non-empty
    # list means the Law 3 proof is incomplete and the probe must be discarded.
    missing: Any = None

    def complete(self) -> bool:
        return (
            self.captured
            and self.balances is not None
            and self.positions is not None
            and self.open_orders is not None
            and not self.missing
        )


class EvidenceRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    record_type: str
    run_id: str
    sequence: int = 0
    label: EvidenceLabel
    occurred_at: datetime = Field(default_factory=utc_now)
    capability: str | None = None
    operation: str | None = None
    source: str | None = None
    request: Any = None
    response: Any = None
    raw_response: str | None = None
    http_status: int | None = None
    error_code: str | None = None
    outcome: str | None = None
    gate: GateOutcome | None = None
    advertised: bool | None = None
    granted_scope: str | None = None
    state_before: StateSnapshot | None = None
    state_after: StateSnapshot | None = None
    state_unchanged: bool | None = None
    control_passed: bool | None = None
    config_sha256: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    prev_hash: str | None = None
    record_hash: str | None = None


class ClassificationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capability: str
    classification: Classification
    label: EvidenceLabel = EvidenceLabel.OBSERVED
    reason: str
    evidence_sequences: list[int] = Field(default_factory=list)
    proof_chain: list[dict[str, Any]] = Field(default_factory=list)


class ProbeDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    scope: str
    product: str
    operation: str
    probe_policy: Literal["non_executing_only"]
    symbol_source: str
    threshold_source: str


class ProbeBudgets(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_probes_per_run: int = Field(gt=0)
    max_probes_per_minute: int = Field(gt=0)
    retry_after_cap_seconds: float = Field(gt=0)
    backoff_base_seconds: float = Field(gt=0)
    backoff_max_seconds: float = Field(gt=0)


class ProbeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int
    claim_label: EvidenceLabel
    budgets: ProbeBudgets
    capabilities: list[ProbeDefinition] = Field(min_length=1)


class StrategyNeeds(BaseModel):
    model_config = ConfigDict(extra="allow")

    account: dict[str, Any] = Field(default_factory=dict)
    trade: dict[str, Any] = Field(default_factory=dict)
    margin: bool = False
    futures: bool = False
    transfer: bool = False


class StrategyConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str
    claim_label: EvidenceLabel
    needs: StrategyNeeds
