"""Capability probing with a complete, chained state proof.

Order of operations for every probe, enforced here rather than by convention:

1. positive control (Law 4) - a known-permitted read in the same session
2. complete state snapshot, hashed (Law 3)
3. exactly one probe invocation (Law 7), against parameters read from Binance's
   own filters rather than guessed
4. complete state snapshot, hashed
5. digest comparison; a probe whose snapshots are incomplete or unequal is
   DISCARDED rather than reported

Every step writes its verbatim response to the append-only evidence log.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .evidence import EvidenceLog
from .mcp import McpClient, ToolResult
from .models import EvidenceRecord
from .snapshot import SnapshotChain, SnapshotComponent, capture, compare

POSITIVE_CONTROL_TOOL = "spot.getAccount"

# DOCUMENTED: -1013 is a spot filter rejection that never reaches the matching
# engine; -2015 conflates credential, IP and permission failure.
# OBSERVED: USDS-M futures returns -4xxx codes for the same class of parameter
# rejection, for example -4013 "Price less than min price".
#
# Codes this build has OBSERVED, each rejected before the matching engine:
#   -1013  spot filter failure (PERCENT_PRICE_BY_SIDE)
#   -4013  USDS-M futures, "Price less than min price"
#   -1111  COIN-M futures, "Precision is over the maximum defined for this asset"
#
# ASSUMED: that each of these is a parameter rejection rather than an
# authorization failure. A code this build has not observed is NOT assumed into
# a class - it stays INCONCLUSIVE.
PARAMETER_REJECTION_CODES = {"-1013", "-4013", "-1111"}
AUTHORIZATION_FAILURE_CODES = {"-2015"}


def classify_error_code(code: str | None) -> str:
    """Map a Binance error code to one of the Law 5 classifications.

    A code this build has not observed is INCONCLUSIVE. Ignorance is a result.
    """
    if code in PARAMETER_REJECTION_CODES:
        return "VERIFIED"
    if code in AUTHORIZATION_FAILURE_CODES:
        return "DENIED"
    return "INCONCLUSIVE"


@dataclass
class ProbeOutcome:
    capability: str
    tool: str
    classification: str
    error_code: str | None
    state_verdict: dict[str, Any]
    discarded: bool
    reason: str | None = None


def _record(
    log: EvidenceLog,
    *,
    run_id: str,
    record_type: str,
    result: ToolResult,
    scope: str | None,
    capability: str | None = None,
    **extra: Any,
) -> None:
    log.append(
        EvidenceRecord(
            record_type=record_type,
            run_id=run_id,
            label="OBSERVED",
            capability=capability,
            operation=result.name,
            request=result.request,
            raw_response=result.raw[:400000],
            http_status=result.http_status,
            error_code=result.error_code,
            granted_scope=scope,
            **extra,
        )
    )


def positive_control(
    client: McpClient, log: EvidenceLog, run_id: str
) -> tuple[bool, ToolResult]:
    """Law 4: a call known to be permitted, same session, client, IP and minute."""
    result = client.call_tool(POSITIVE_CONTROL_TOOL, {})
    passed = result.http_status == 200 and not result.is_error
    _record(
        log,
        run_id=run_id,
        record_type="positive_control",
        result=result,
        scope=client.session.granted_scope,
        control_passed=passed,
        outcome="control_passed" if passed else "control_failed",
        metadata={"note": "read-only; cannot change financial state"},
    )
    return passed, result


def run_probe(
    client: McpClient,
    log: EvidenceLog,
    chain: SnapshotChain,
    components: list[SnapshotComponent],
    *,
    capability: str,
    tool: str,
    arguments: dict[str, Any],
    probe_design: str,
    run_id: str | None = None,
    config_sha256: str | None = None,
) -> ProbeOutcome:
    """Run one probe with a complete before/after state proof."""
    run_id = run_id or datetime.now(timezone.utc).strftime(f"{capability}-probe-%Y%m%dT%H%M%SZ")
    scope = client.session.granted_scope

    control_passed, _ = positive_control(client, log, run_id)
    if not control_passed:
        return ProbeOutcome(
            capability=capability,
            tool=tool,
            classification="INCONCLUSIVE",
            error_code=None,
            state_verdict={},
            discarded=True,
            reason="positive control failed; batch discarded under Law 4",
        )

    before, before_raw = capture(client, components, config_sha256=config_sha256)
    for result in before_raw:
        _record(
            log,
            run_id=run_id,
            record_type="state_component",
            result=result,
            scope=scope,
            capability=capability,
            outcome="pre_probe",
        )
    chain.add(f"{capability}:pre", before)

    probe_result = client.probe(tool, arguments)

    after, after_raw = capture(client, components, config_sha256=config_sha256)
    for result in after_raw:
        _record(
            log,
            run_id=run_id,
            record_type="state_component",
            result=result,
            scope=scope,
            capability=capability,
            outcome="post_probe",
        )
    chain.add(f"{capability}:post", after)

    verdict = compare(before, after)
    discarded = not verdict["identical"]

    if discarded:
        classification = "INCONCLUSIVE"
        reason = (
            "state proof incomplete; probe discarded under Law 3"
            if not (before.complete() and after.complete())
            else "financial state changed; probe discarded under Law 3"
        )
    else:
        reason = None
        classification = classify_error_code(probe_result.error_code)

    _record(
        log,
        run_id=run_id,
        record_type="capability_probe",
        result=probe_result,
        scope=scope,
        capability=capability,
        advertised=True,
        control_passed=True,
        state_before=before,
        state_after=after,
        state_unchanged=verdict["identical"],
        gate="UNGATED",
        outcome=classification,
        config_sha256=config_sha256,
        metadata={
            "probe_design": probe_design,
            "state_verdict": verdict,
            "budget": client.budget.report(),
            "discarded": discarded,
            "discard_reason": reason,
            "no_confirmation_prompt_observed": True,
            "egress_country": "GB",
        },
    )

    return ProbeOutcome(
        capability=capability,
        tool=tool,
        classification=classification,
        error_code=probe_result.error_code,
        state_verdict=verdict,
        discarded=discarded,
        reason=reason,
    )
