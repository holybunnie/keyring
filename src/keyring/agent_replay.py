"""Read-only reconstruction of a retained model-planned agent run."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path
from typing import Any, Mapping, cast

from .evidence import EvidenceIntegrityError, EvidenceLog
from .models import EvidenceRecord
from .planner import ProbeProposal, ProposalRejected, validate_proposal

DEFAULT_EVIDENCE_DIR = Path("evidence/raw")
DEFAULT_SOURCE_REF = "0012-codex-cli-second-account.jsonl#78"


class AgentReplayError(ValueError):
    """The retained evidence cannot support a complete agent replay."""


def _ref(filename: str, sequence: int) -> str:
    return f"{filename}#{sequence}"


def _decoded_response(record: EvidenceRecord) -> Any:
    if record.response is not None:
        return record.response
    if not record.raw_response:
        return None
    try:
        body = json.loads(record.raw_response)
    except (TypeError, ValueError):
        return None
    if not isinstance(body, dict):
        return body
    result = body.get("result", body)
    if isinstance(result, dict):
        content = result.get("content")
        if isinstance(content, list) and content and isinstance(content[0], dict):
            text = content[0].get("text")
            if isinstance(text, str):
                try:
                    return json.loads(text)
                except (TypeError, ValueError):
                    return text
    return result


def _all_records(evidence_dir: str | Path) -> list[tuple[str, EvidenceRecord]]:
    path = Path(evidence_dir)
    if not path.is_dir():
        raise AgentReplayError(f"evidence directory does not exist: {path}")
    records: list[tuple[str, EvidenceRecord]] = []
    try:
        for file in sorted(path.glob("*.jsonl")):
            records.extend((file.name, record) for record in EvidenceLog(file).records())
    except EvidenceIntegrityError as error:
        raise AgentReplayError(f"evidence integrity check failed: {error}") from error
    return records


def _select_probe(
    records: list[tuple[str, EvidenceRecord]], source_ref: str | None
) -> tuple[str, EvidenceRecord]:
    candidates = [
        item
        for item in records
        if item[1].record_type == "capability_probe"
        and item[1].planned_by == "model"
        and item[1].model_proposal is not None
    ]
    selected_ref = source_ref or DEFAULT_SOURCE_REF
    if selected_ref:
        wanted_file, separator, wanted_sequence = selected_ref.rpartition("#")
        if not separator or not wanted_sequence.isdigit():
            raise AgentReplayError("--ref must use FILE#SEQUENCE")
        candidates = [
            item
            for item in candidates
            if (item[0] == wanted_file or Path(item[0]).stem == wanted_file)
            and item[1].sequence == int(wanted_sequence)
        ]
    if len(candidates) != 1:
        detail = "no matching" if not candidates else f"{len(candidates)} matching"
        raise AgentReplayError(f"expected one model-planned probe; found {detail} records")
    return candidates[0]


def _tool_list(record: EvidenceRecord) -> list[Mapping[str, Any]]:
    payload = _decoded_response(record)
    if not isinstance(payload, Mapping):
        return []
    tools = payload.get("tools")
    if not isinstance(tools, list):
        return []
    return [tool for tool in tools if isinstance(tool, Mapping)]


def _symbol_filters(record: EvidenceRecord, symbol: str) -> list[Mapping[str, Any]]:
    payload = _decoded_response(record)
    if not isinstance(payload, Mapping):
        return []
    symbols = payload.get("symbols")
    if not isinstance(symbols, list):
        return []
    matches = [
        item
        for item in symbols
        if isinstance(item, Mapping)
        and str(item.get("symbol", "")).upper() == symbol.upper()
    ]
    if len(matches) != 1 or not isinstance(matches[0].get("filters"), list):
        return []
    return [
        item for item in matches[0]["filters"] if isinstance(item, Mapping)
    ]


def _binance_message(raw_response: str | None) -> str | None:
    if not raw_response:
        return None
    try:
        body: Any = json.loads(raw_response)
        message = body.get("error", {}).get("message") if isinstance(body, dict) else None
        if isinstance(message, str):
            try:
                nested = json.loads(message)
            except ValueError:
                return message
            if isinstance(nested, dict) and nested.get("msg"):
                return str(nested["msg"])
    except (TypeError, ValueError):
        pass
    return None


def replay(
    evidence_dir: str | Path = DEFAULT_EVIDENCE_DIR,
    *,
    source_ref: str | None = None,
) -> dict[str, Any]:
    """Verify and reconstruct one recorded run without network calls or writes."""
    records = _all_records(evidence_dir)
    filename, probe = _select_probe(records, source_ref)
    proposal_data = probe.model_proposal or {}
    tool_name = str(proposal_data.get("tool_name", ""))
    symbol = str(proposal_data.get("symbol", ""))
    arguments = proposal_data.get("arguments")
    if not tool_name or not symbol or not isinstance(arguments, dict):
        raise AgentReplayError("recorded model proposal is incomplete")

    preceding = [
        (name, record)
        for name, record in records
        if name == filename
        and record.run_id == probe.run_id
        and record.sequence < probe.sequence
    ]
    schema_matches = [
        (name, record, tool)
        for name, record in preceding
        if record.record_type in {"tools_list", "mcp_discovery"}
        for tool in _tool_list(record)
        if tool.get("name") == tool_name
    ]
    if not schema_matches:
        raise AgentReplayError(f"no retained runtime schema for {tool_name}")
    schema_filename, schema_record, schema = max(
        schema_matches, key=lambda item: item[1].sequence
    )

    filter_matches = [
        (name, record, filters)
        for name, record in preceding
        if record.record_type == "symbol_filters"
        and record.capability == probe.capability
        and (filters := _symbol_filters(record, symbol))
    ]
    if not filter_matches:
        raise AgentReplayError(f"no retained live filters for {symbol}")
    filters_filename, filters_record, filters = max(
        filter_matches, key=lambda item: item[1].sequence
    )

    proposal = ProbeProposal(
        tool_name=tool_name,
        arguments=arguments,
        symbol=symbol,
        expected_filter=str(proposal_data.get("expected_filter", "")),
        justification=str(proposal_data.get("justification", "")),
        planned_by="model",
        model_payload=cast(dict[str, Any] | None, proposal_data.get("model_payload")),
    )
    validation = validate_proposal(
        proposal,
        schema,
        filters,
        discovered_tool_names=[tool_name],
    )
    if not validation.valid:
        raise ProposalRejected(
            "recorded proposal no longer passes the deterministic gate: "
            + "; ".join(validation.reasons)
        )

    expected_filter = proposal.expected_filter.upper()
    matching_filter = next(
        (
            dict(item)
            for item in filters
            if str(item.get("filterType", "")).upper() == expected_filter
        ),
        None,
    )
    probe_ref = _ref(filename, probe.sequence)
    schema_ref = _ref(schema_filename, schema_record.sequence)
    filters_ref = _ref(filters_filename, filters_record.sequence)
    controls = [
        (name, record)
        for name, record in preceding
        if record.record_type == "positive_control"
        and record.control_passed is True
    ]
    control_ref = None
    control_sequence = 0
    if controls:
        control_filename, control_record = max(
            controls, key=lambda item: item[1].sequence
        )
        control_ref = _ref(control_filename, control_record.sequence)
        control_sequence = control_record.sequence
    state_sources = [
        _ref(name, record.sequence)
        for name, record in preceding
        if record.capability == probe.capability
        and record.record_type == "state_component"
        and record.sequence > control_sequence
    ]
    interpretation = probe.model_interpretation or {}
    model_view = interpretation.get("proposal")
    input_schema = schema.get("inputSchema")
    required_arguments = (
        input_schema.get("required", [])
        if isinstance(input_schema, Mapping)
        else []
    )
    request_arguments = None
    if isinstance(probe.request, Mapping):
        params = probe.request.get("params")
        if isinstance(params, Mapping):
            request_arguments = params.get("arguments")
    return {
        "mode": "RECORDED_REPLAY",
        "network_calls": 0,
        "evidence_mutated": False,
        "evidence_chains_verified": True,
        "run_id": probe.run_id,
        "runtime_schema": {
            "tool": tool_name,
            "required_arguments": required_arguments,
            "source": schema_ref,
        },
        "live_filters": {
            "symbol": symbol,
            "expected_violation": expected_filter,
            "filter": matching_filter,
            "source": filters_ref,
        },
        "model_proposal": {
            "tool": tool_name,
            "arguments": arguments,
            "expected_violation": expected_filter,
            "reasoning": proposal.justification,
            "planned_by": "model",
            "source": probe_ref,
        },
        "deterministic_gate": {
            "result": "ACCEPTED AS NON-EXECUTING TEST",
            "notional": validation.notional,
            "minimum_notional": validation.min_notional,
            "violated_filters": list(validation.violated_filters),
            "recomputed": True,
            "sources": [schema_ref, filters_ref, probe_ref],
        },
        "controlled_request": {
            "tool": probe.operation,
            "arguments": request_arguments,
            "positive_control_passed": control_ref is not None,
            "positive_control_source": control_ref,
            "source": probe_ref,
        },
        "binance_response": {
            "error_code": probe.error_code,
            "message": _binance_message(probe.raw_response),
            "source": probe_ref,
        },
        "model_interpretation": {
            "used": bool(model_view),
            "classification": model_view.get("classification")
            if isinstance(model_view, Mapping)
            else None,
            "reason": model_view.get("reason")
            if isinstance(model_view, Mapping)
            else None,
            "source": probe_ref,
        },
        "deterministic_result": {
            "classification": interpretation.get("final_classification", probe.outcome),
            "classifier_decision": interpretation.get(
                "classifier_decision", probe.outcome
            ),
            "disagreement": bool(interpretation.get("disagreement")),
            "source": probe_ref,
        },
        "account_state": {
            "before_digest": probe.state_before.digest if probe.state_before else None,
            "after_digest": probe.state_after.digest if probe.state_after else None,
            "unchanged": probe.state_unchanged,
            "complete": bool(
                probe.state_before
                and probe.state_after
                and probe.state_before.complete()
                and probe.state_after.complete()
            ),
            "component_sources": state_sources,
            "verdict_source": probe_ref,
        },
    }


def _wrapped(label: str, value: Any, *, indent: int = 3) -> str:
    prefix = " " * indent + label
    width = max(40, 88 - len(prefix))
    lines = textwrap.wrap(str(value), width=width) or ["—"]
    return prefix + lines[0] + "\n" + "\n".join(
        " " * len(prefix) + line for line in lines[1:]
    )


def render(result: Mapping[str, Any]) -> str:
    """Render a concise judge-facing transcript with provenance at every step."""
    schema = result["runtime_schema"]
    filters = result["live_filters"]
    proposal = result["model_proposal"]
    gate = result["deterministic_gate"]
    request = result["controlled_request"]
    response = result["binance_response"]
    interpretation = result["model_interpretation"]
    deterministic = result["deterministic_result"]
    state = result["account_state"]
    state_sources = state["component_sources"]
    state_ref = (
        f"{state_sources[0]} through {state_sources[-1]}"
        if state_sources
        else "not recorded"
    )
    model_class = interpretation["classification"] or "not used"
    return "\n".join(
        [
            "KEYRING AGENT — RECORDED RUN",
            "Verified retained evidence only · no network · no reconnect · no mutation",
            "",
            "1. Runtime Binance tool schema",
            f"   {schema['tool']}",
            f"   required: {', '.join(schema['required_arguments']) or 'none'}",
            f"   source: {schema['source']}",
            "",
            "2. Live filters captured in this run",
            f"   {filters['symbol']} · expected violation: {filters['expected_violation']}",
            f"   filter: {json.dumps(filters['filter'], sort_keys=True, default=str)}",
            f"   source: {filters['source']}",
            "",
            "3. Recorded model proposal",
            f"   tool: {proposal['tool']}",
            f"   arguments: {json.dumps(proposal['arguments'], sort_keys=True)}",
            f"   planned_by: {proposal['planned_by']}",
            _wrapped("reasoning: ", proposal["reasoning"]),
            f"   source: {proposal['source']}",
            "",
            "4. Deterministic non-execution gate",
            f"   {gate['result']}",
            f"   violated filter: {', '.join(gate['violated_filters'])}",
            "   recomputed from retained schema + filters + proposal",
            f"   sources: {', '.join(gate['sources'])}",
            "",
            "5. Controlled Binance request",
            f"   connection check passed: {'yes' if request['positive_control_passed'] else 'no'}",
            f"   connection-check source: {request['positive_control_source'] or 'not recorded'}",
            f"   {request['tool']} {json.dumps(request['arguments'], sort_keys=True)}",
            f"   source: {request['source']}",
            "",
            "6. Binance validation response",
            f"   {response['error_code']} · {response['message'] or 'message unavailable'}",
            f"   source: {response['source']}",
            "",
            "7. Recorded model interpretation",
            f"   {model_class}",
            _wrapped("reason: ", interpretation["reason"] or "not used"),
            f"   source: {interpretation['source']}",
            "",
            "8. Deterministic result",
            f"   {deterministic['classification']}",
            f"   disagreement preserved: {'yes' if deterministic['disagreement'] else 'no'}",
            f"   source: {deterministic['source']}",
            "",
            "9. Account state proof",
            f"   before == after {'✓' if state['unchanged'] and state['complete'] else '✕'}",
            f"   components: {state_ref}",
            f"   verdict source: {state['verdict_source']}",
            "",
            "The deterministic result wins.",
        ]
    )
