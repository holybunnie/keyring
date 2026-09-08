"""Model-assisted probe planning with a deterministic send gate.

The model sees a discovered tool schema, live symbol filters, the capability
under test, and prior probe history. It can propose arguments and a reason. It
cannot send them. ``validate_proposal`` is the hard gate: a proposal must use a
discovered write tool, satisfy the schema's required fields, use the requested
symbol, and violate a live rejection filter in a way that cannot execute.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Literal, Mapping

from .model_client import TextModel

WRITE_VERBS = (
    "new",
    "cancel",
    "delete",
    "change",
    "transfer",
    "borrow",
    "repay",
    "place",
    "accept",
)


class PlannerError(ValueError):
    """A proposal cannot safely be used as a probe."""


class ProposalRejected(PlannerError):
    """The model or static planner did not pass the deterministic gate."""


@dataclass(frozen=True)
class ProbeProposal:
    tool_name: str
    arguments: dict[str, Any]
    symbol: str
    expected_filter: str
    justification: str
    planned_by: Literal["model", "static"]
    model_payload: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        result = {
            "tool_name": self.tool_name,
            "arguments": self.arguments,
            "symbol": self.symbol,
            "expected_filter": self.expected_filter,
            "justification": self.justification,
            "planned_by": self.planned_by,
        }
        if self.model_payload is not None:
            result["model_payload"] = self.model_payload
        return result


@dataclass(frozen=True)
class ProposalValidation:
    valid: bool
    reasons: tuple[str, ...] = ()
    notional: str | None = None
    min_notional: str | None = None
    violated_filters: tuple[str, ...] = ()


def _decimal(value: Any) -> Decimal | None:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _filter_number(filter_value: Mapping[str, Any] | None, *keys: str) -> Decimal | None:
    if not filter_value:
        return None
    for key in keys:
        if key in filter_value:
            value = _decimal(filter_value.get(key))
            if value is not None:
                return value
    return None


def _normalize_numeric_arguments(arguments: Mapping[str, Any]) -> dict[str, Any]:
    """Keep model-proposed decimal values out of scientific JSON notation."""
    normalized = dict(arguments)
    for name, value in normalized.items():
        if isinstance(value, float):
            decimal = _decimal(value)
            if decimal is not None:
                normalized[name] = format(decimal, "f")
    return normalized


def _operation(name: str) -> str:
    return name.rsplit(".", 1)[-1].lower()


def _is_write_tool(name: str) -> bool:
    return _operation(name).startswith(WRITE_VERBS)


def _input_schema(tool_schema: Mapping[str, Any]) -> Mapping[str, Any]:
    schema = tool_schema.get("inputSchema", tool_schema)
    return schema if isinstance(schema, Mapping) else {}


def _filter_list(filters: Any) -> list[Mapping[str, Any]]:
    if isinstance(filters, Mapping) and isinstance(filters.get("filters"), list):
        filters = filters["filters"]
    if isinstance(filters, list):
        return [item for item in filters if isinstance(item, Mapping)]
    if isinstance(filters, Mapping):
        result = []
        for name, value in filters.items():
            if isinstance(value, Mapping):
                result.append({"filterType": name, **value})
        return result
    return []


def _find_filter(filters: Any, *names: str) -> Mapping[str, Any] | None:
    wanted = {name.upper() for name in names}
    for item in _filter_list(filters):
        if str(item.get("filterType", "")).upper() in wanted:
            return item
    return None


def _filter_names(filters: Any) -> set[str]:
    return {str(item.get("filterType", "")).upper() for item in _filter_list(filters)}


def _number_argument(arguments: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        if name in arguments:
            return arguments[name]
    return None


def _json_object(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(line for line in lines if not line.strip().startswith("```")).strip()
    decoder = json.JSONDecoder()
    for index, character in enumerate(text):
        if character != "{":
            continue
        try:
            value, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise PlannerError("model response did not contain a JSON object")


def validate_proposal(
    proposal: ProbeProposal,
    tool_schema: Mapping[str, Any],
    filters: Any,
    *,
    discovered_tool_names: Iterable[str] | None = None,
) -> ProposalValidation:
    """Deterministically decide whether a proposal is safe to send."""
    reasons: list[str] = []
    arguments = proposal.arguments
    schema = _input_schema(tool_schema)
    required = schema.get("required", [])
    if not isinstance(required, list):
        required = []
    if not proposal.tool_name or not _is_write_tool(proposal.tool_name):
        reasons.append("proposal is not a write-shaped tool")
    if discovered_tool_names is not None and proposal.tool_name not in set(discovered_tool_names):
        reasons.append("tool is not present in the discovered surface")
    schema_tool_name = tool_schema.get("name")
    if schema_tool_name and proposal.tool_name != schema_tool_name:
        reasons.append("proposal tool does not match the supplied tool schema")
    for name in required:
        if name not in arguments:
            reasons.append(f"required argument missing: {name}")
    symbol_value = arguments.get("symbol")
    if symbol_value is None:
        reasons.append("symbol argument is required for a bounded probe")
    elif str(symbol_value).upper() != proposal.symbol.upper():
        reasons.append("argument symbol does not match the planned symbol")

    min_filter = _find_filter(filters, "MIN_NOTIONAL", "NOTIONAL")
    min_notional = _filter_number(min_filter, "minNotional", "notional")
    if min_filter and (min_notional is None or min_notional <= 0):
        reasons.append("live notional filter is present but invalid")

    quantity = _decimal(_number_argument(arguments, "quantity", "qty", "origQty"))
    price = _decimal(_number_argument(arguments, "price"))
    quote_quantity = _decimal(_number_argument(arguments, "quoteOrderQty"))
    notional = quote_quantity if quote_quantity is not None else (
        quantity * price if quantity is not None and price is not None else None
    )
    if notional is None or notional <= 0:
        reasons.append("positive quantity and price/quoteOrderQty are required")
    elif min_notional is not None and notional >= min_notional:
        reasons.append("notional is not below the live MIN_NOTIONAL filter")

    expected = proposal.expected_filter.upper()
    available = _filter_names(filters)
    notional_filters = {"MIN_NOTIONAL", "NOTIONAL"}
    safe_filters = notional_filters | {"PRICE_FILTER", "LOT_SIZE", "MARKET_LOT_SIZE"}
    # Every accepted proposal must identify a live filter that guarantees
    # rejection. Notional is the strongest invariant when available; COIN-M
    # exchange information has no notional filter, so a price/lot lower bound
    # is used instead.
    if expected not in safe_filters:
        reasons.append("expected filter is not a supported live rejection filter")
    elif expected not in available:
        reasons.append("expected rejection filter is not present in live symbol filters")
    elif expected in notional_filters:
        if min_notional is None or min_notional <= 0:
            reasons.append("expected notional filter is missing or invalid")
    elif expected == "PRICE_FILTER":
        price_filter = _find_filter(filters, "PRICE_FILTER") or {}
        min_price = _decimal(price_filter.get("minPrice"))
        max_price = _decimal(price_filter.get("maxPrice"))
        if price is None or price <= 0:
            reasons.append("a positive price is required for a price-filter probe")
        elif (min_price is None or price >= min_price) and (
            max_price is None or price <= max_price
        ):
            reasons.append("price does not violate the live PRICE_FILTER")
    else:
        lot_filter = _find_filter(filters, expected) or {}
        min_qty = _decimal(lot_filter.get("minQty"))
        max_qty = _decimal(lot_filter.get("maxQty"))
        if quantity is None or quantity <= 0:
            reasons.append("a positive quantity is required for a lot-size probe")
        elif (min_qty is None or quantity >= min_qty) and (
            max_qty is None or quantity <= max_qty
        ):
            reasons.append("quantity does not violate the live lot-size filter")
    if not proposal.symbol.strip():
        reasons.append("planned symbol is empty")
    if not proposal.justification.strip():
        reasons.append("probe justification is empty")

    return ProposalValidation(
        valid=not reasons,
        reasons=tuple(reasons),
        notional=str(notional) if notional is not None else None,
        min_notional=str(min_notional) if min_notional is not None else None,
        violated_filters=(expected,) if not reasons else (),
    )


def static_proposal(
    *,
    tool_name: str,
    tool_schema: Mapping[str, Any],
    symbol: str,
    filters: Any,
) -> ProbeProposal:
    """Make a conservative, deterministic proposal for offline operation."""
    schema = _input_schema(tool_schema)
    properties = schema.get("properties", {})
    if not isinstance(properties, Mapping):
        properties = {}
    required = schema.get("required", [])
    if not isinstance(required, list):
        required = []
    min_filter = _find_filter(filters, "MIN_NOTIONAL", "NOTIONAL")
    min_notional = _filter_number(min_filter, "minNotional", "notional")
    lot_filter = _find_filter(filters, "LOT_SIZE")
    qty = _decimal(lot_filter.get("minQty") if lot_filter else None) or Decimal("0.00001")
    expected_filter = "MIN_NOTIONAL"
    if min_notional is not None and min_notional > 0:
        price = min_notional / (qty * Decimal(2))
        justification = (
            f"positive notional {qty * price} is below the live MIN_NOTIONAL "
            f"threshold {min_notional} for {symbol}"
        )
    else:
        price_filter = _find_filter(filters, "PRICE_FILTER")
        min_price = _decimal(price_filter.get("minPrice") if price_filter else None)
        if min_price is None or min_price <= 0:
            raise ProposalRejected(
                "cannot make a static proposal without a valid notional or price filter"
            )
        price = min_price / Decimal(2)
        expected_filter = "PRICE_FILTER"
        justification = (
            f"price {price} is below the live PRICE_FILTER minimum {min_price} "
            f"for {symbol}; the order is rejected before execution"
        )
    arguments: dict[str, Any] = {}
    for name in required:
        if name == "symbol":
            arguments[name] = symbol
        elif name == "side":
            arguments[name] = "BUY"
        elif name == "type":
            arguments[name] = "LIMIT"
        elif name == "timeInForce":
            arguments[name] = "GTC"
        elif name in {"quantity", "qty", "origQty"}:
            arguments[name] = format(qty, "f")
        elif name == "price":
            arguments[name] = format(price, "f")
        elif name == "quoteOrderQty":
            arguments[name] = format(min_notional / Decimal(2), "f")
        else:
            raise ProposalRejected(f"static planner cannot fill required argument: {name}")
    if "symbol" in properties:
        arguments.setdefault("symbol", symbol)
    if "quantity" in properties:
        arguments.setdefault("quantity", format(qty, "f"))
    if "price" in properties:
        arguments.setdefault("price", format(price, "f"))
    proposal = ProbeProposal(
        tool_name=tool_name,
        arguments=arguments,
        symbol=symbol,
        expected_filter=expected_filter,
        justification=justification,
        planned_by="static",
    )
    validation = validate_proposal(proposal, tool_schema, filters, discovered_tool_names=[tool_name])
    if not validation.valid:
        raise ProposalRejected("static proposal rejected: " + "; ".join(validation.reasons))
    return proposal


def planner_prompt(
    *,
    capability: str,
    symbol: str,
    tool_schema: Mapping[str, Any],
    filters: Any,
    history: Iterable[Mapping[str, Any]] = (),
    feedback: Iterable[str] = (),
) -> str:
    return json.dumps(
        {
            "task": "propose one non-executing capability probe",
            "capability": capability,
            "symbol": symbol,
            "tool_schema": tool_schema,
            "live_symbol_filters": filters,
            "prior_probe_history": list(history),
            "validator_feedback": list(feedback),
            "output": {
                "tool_name": "discovered write tool name",
                "arguments": "complete arguments object",
                "symbol": symbol,
                "expected_filter": "one filterType present in live_symbol_filters",
                "justification": (
                    "why the selected live filter is guaranteed to reject the "
                    "positive order before execution"
                ),
            },
        },
        indent=2,
        default=str,
    )


class ProbePlanner:
    """Return only proposals that have passed the deterministic validator."""

    def __init__(self, model: TextModel | None = None, *, max_attempts: int = 2):
        self.model = model
        self.max_attempts = max_attempts

    def plan(
        self,
        *,
        capability: str,
        tool_schema: Mapping[str, Any],
        tool_name: str | None = None,
        symbol: str,
        filters: Any,
        discovered_tool_names: Iterable[str] | None = None,
        history: Iterable[Mapping[str, Any]] = (),
    ) -> ProbeProposal:
        history = list(history)
        discovered_names = (
            list(discovered_tool_names)
            if discovered_tool_names is not None
            else None
        )
        if self.model is None:
            proposal = static_proposal(
                tool_name=tool_name or str(tool_schema.get("name", "")),
                tool_schema=tool_schema,
                symbol=symbol,
                filters=filters,
            )
            validation = validate_proposal(
                proposal,
                tool_schema,
                filters,
                discovered_tool_names=discovered_names,
            )
            if not validation.valid:
                raise ProposalRejected("static proposal rejected: " + "; ".join(validation.reasons))
            return proposal

        feedback: list[str] = []
        for _ in range(max(self.max_attempts, 1)):
            try:
                raw = self.model.complete(
                    system=(
                        "You are the KEYRING probe planner. Return JSON only. "
                        "You propose arguments; deterministic code decides whether anything is sent. "
                        "Never propose an executable order."
                    ),
                    user=planner_prompt(
                        capability=capability,
                        symbol=symbol,
                        tool_schema=tool_schema,
                        filters=filters,
                        history=history,
                        feedback=feedback,
                    ),
                )
                payload = _json_object(raw)
            except Exception as error:  # noqa: BLE001 - retry with explicit feedback
                feedback = [f"model proposal could not be parsed: {error}"]
                continue
            raw_arguments = payload.get("arguments")
            arguments = (
                _normalize_numeric_arguments(raw_arguments)
                if isinstance(raw_arguments, dict)
                else {}
            )
            proposal = ProbeProposal(
                tool_name=str(payload.get("tool_name", "")),
                arguments=arguments,
                symbol=str(payload.get("symbol") or symbol),
                expected_filter=str(payload.get("expected_filter", "")),
                justification=str(payload.get("justification", "")),
                planned_by="model",
                model_payload=payload,
            )
            validation = validate_proposal(
                proposal,
                tool_schema,
                filters,
                discovered_tool_names=discovered_names,
            )
            if validation.valid:
                return proposal
            feedback = list(validation.reasons)
        raise ProposalRejected("model proposal rejected: " + "; ".join(feedback))
