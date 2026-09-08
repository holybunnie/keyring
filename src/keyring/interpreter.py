"""Narrow model assistance for gateway responses.

Known codes are handled without a model. An unmatched response may be shown to
Claude for an interpretation, but the final classifier remains
``INCONCLUSIVE`` unless a deterministic rule already recognizes the response.
Both the model proposal and deterministic decision are returned for evidence.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from .evidence import redact_raw
from .model_client import TextModel
from .prober import classify_error_code

ALLOWED_CLASSES = {"VERIFIED", "DENIED", "ADVERTISED_ONLY", "INCONCLUSIVE"}


@dataclass(frozen=True)
class Interpretation:
    classifier_decision: str
    model_classification: str | None = None
    model_reason: str | None = None
    model_assisted: bool = False
    disagreement: bool = False
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "model_assisted": self.model_assisted,
            "classifier_decision": self.classifier_decision,
            "final_classification": self.classifier_decision,
            "disagreement": self.disagreement,
        }
        if self.model_classification is not None:
            result["proposal"] = {
                "classification": self.model_classification,
                "reason": self.model_reason or "",
            }
        if self.error:
            result["error"] = self.error
        return result


def _json_object(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        text = "\n".join(
            line for line in text.splitlines() if not line.strip().startswith("```")
        ).strip()
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
    raise ValueError("model response did not contain a JSON object")


def deterministic_classification(error_code: str | None, outcome: str | None = None) -> str:
    if (outcome or "").lower() == "advertised_only":
        return "ADVERTISED_ONLY"
    return classify_error_code(error_code)


class ResponseInterpreter:
    def __init__(self, model: TextModel | None = None):
        self.model = model

    def interpret(
        self,
        *,
        raw_response: str,
        error_code: str | None,
        outcome: str | None = None,
        context: Mapping[str, Any] | None = None,
    ) -> Interpretation:
        decision = deterministic_classification(error_code, outcome)
        if decision != "INCONCLUSIVE" or self.model is None:
            return Interpretation(classifier_decision=decision)

        prompt = json.dumps(
            {
                "task": "interpret an unmatched Binance Agentic gateway response",
                "response": redact_raw(raw_response or "")[-20000:],
                "error_code_extracted_deterministically": error_code,
                "context": dict(context or {}),
                "output": {
                    "classification": "VERIFIED, DENIED, ADVERTISED_ONLY, or INCONCLUSIVE",
                    "reason": "short explanation",
                },
            },
            indent=2,
            default=str,
        )
        try:
            raw = self.model.complete(
                system=(
                    "You are the KEYRING response interpreter. Return JSON only. "
                    "Your result is a proposal; deterministic KEYRING code makes the final decision."
                ),
                user=prompt,
            )
            payload = _json_object(raw)
            proposed = str(payload.get("classification", "")).upper()
            reason = str(payload.get("reason", ""))
            if proposed not in ALLOWED_CLASSES:
                raise ValueError("model proposed an unsupported classification")
            return Interpretation(
                classifier_decision=decision,
                model_classification=proposed,
                model_reason=reason,
                model_assisted=True,
                disagreement=proposed != decision,
            )
        except Exception as error:  # noqa: BLE001 - model never changes the final class
            return Interpretation(
                classifier_decision=decision,
                model_assisted=True,
                error=str(error),
            )
