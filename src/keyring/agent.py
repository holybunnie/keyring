"""The deliberately narrow KEYRING agent boundary.

The agent can plan a probe or coordinate that plan through the existing safe
probe runner. A :class:`~keyring.interpreter.ResponseInterpreter` may also ask
Claude to explain an otherwise-unmatched response; the deterministic validator
and classifier still own what is sent and what is published.

The model adapter has no Binance client and this module never gives it one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Iterable, Mapping

from .interpreter import ResponseInterpreter
from .model_client import TextModel
from .planner import (
    ProbePlanner,
    ProbeProposal,
    ProposalRejected,
    ProposalValidation,
    validate_proposal,
)

if TYPE_CHECKING:
    from .evidence import EvidenceLog
    from .mcp import McpClient
    from .prober import ProbeOutcome
    from .snapshot import SnapshotChain, SnapshotComponent


@dataclass(frozen=True)
class PlannedProbe:
    """A proposal plus the final deterministic validation result."""

    proposal: ProbeProposal
    validation: ProposalValidation

    def as_dict(self) -> dict[str, Any]:
        return {
            "proposal": self.proposal.as_dict(),
            "validation": {
                "valid": self.validation.valid,
                "reasons": list(self.validation.reasons),
                "notional": self.validation.notional,
                "min_notional": self.validation.min_notional,
                "violated_filters": list(self.validation.violated_filters),
            },
        }


class KeyringAgent:
    """Coordinate model proposals without granting the model tool access."""

    def __init__(
        self, model: TextModel | None = None, *, max_attempts: int = 2
    ) -> None:
        self.planner = ProbePlanner(model, max_attempts=max_attempts)
        self.interpreter = ResponseInterpreter(model)

    def plan_probe(
        self,
        *,
        capability: str,
        tool_schema: Mapping[str, Any],
        tool_name: str | None = None,
        symbol: str,
        filters: Any,
        discovered_tool_names: Iterable[str] | None = None,
        history: Iterable[Mapping[str, Any]] = (),
    ) -> PlannedProbe:
        discovered_names = (
            list(discovered_tool_names)
            if discovered_tool_names is not None
            else None
        )
        proposal = self.planner.plan(
            capability=capability,
            tool_schema=tool_schema,
            tool_name=tool_name,
            symbol=symbol,
            filters=filters,
            discovered_tool_names=discovered_names,
            history=history,
        )
        # Re-run the gate at the boundary.  This is intentionally redundant:
        # callers receive no proposal that has not passed the same deterministic
        # checks immediately before any caller may send it.
        validation = validate_proposal(
            proposal,
            tool_schema,
            filters,
            discovered_tool_names=discovered_names,
        )
        if not validation.valid:
            raise ProposalRejected(
                "boundary validation rejected proposal: "
                + "; ".join(validation.reasons)
            )
        return PlannedProbe(proposal=proposal, validation=validation)

    def run_probe(
        self,
        client: McpClient,
        log: EvidenceLog,
        chain: SnapshotChain,
        components: list[SnapshotComponent],
        *,
        capability: str,
        tool_schema: Mapping[str, Any],
        symbol: str,
        filters: Any,
        tool_name: str | None = None,
        discovered_tool_names: Iterable[str] | None = None,
        history: Iterable[Mapping[str, Any]] = (),
        run_id: str | None = None,
        config_sha256: str | None = None,
    ) -> ProbeOutcome:
        """Plan, validate, and then enter the existing safety-wrapped probe.

        The planner completes before the first state-changing-shaped request is
        allowed. The returned proposal is passed as evidence metadata, while
        :func:`keyring.prober.run_probe` remains the only execution path.
        """
        from .prober import run_probe as execute_probe

        planned = self.plan_probe(
            capability=capability,
            tool_schema=tool_schema,
            tool_name=tool_name,
            symbol=symbol,
            filters=filters,
            discovered_tool_names=discovered_tool_names,
            history=history,
        )
        proposal = planned.proposal
        return execute_probe(
            client,
            log,
            chain,
            components,
            capability=capability,
            tool=proposal.tool_name,
            arguments=proposal.arguments,
            probe_design=proposal.justification,
            run_id=run_id,
            config_sha256=config_sha256,
            planned_by=proposal.planned_by,
            probe_justification=proposal.justification,
            model_proposal=proposal.as_dict() if proposal.planned_by == "model" else None,
            interpreter=self.interpreter,
        )
