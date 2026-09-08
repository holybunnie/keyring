from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterable

from pydantic import ValidationError

from .models import EvidenceRecord


class EvidenceIntegrityError(ValueError):
    pass


_SENSITIVE_KEY_PARTS = (
    "api-key",
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "password",
    "secret",
    "signature",
    "token",
)
_RAW_SECRET_PATTERNS = (
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+"),
    re.compile(r'(?i)("(?:api[_-]?key|secret|signature|token|authorization)"\s*:\s*")[^"]*(")'),
)


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        result: dict[Any, Any] = {}
        for key, item in value.items():
            key_text = str(key).lower()
            if any(part in key_text for part in _SENSITIVE_KEY_PARTS):
                result[key] = "[REDACTED]"
            else:
                result[key] = redact(item)
        return result
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, tuple):
        return [redact(item) for item in value]
    return value


def redact_raw(value: str | None) -> str | None:
    if value is None:
        return None
    result = value
    result = _RAW_SECRET_PATTERNS[0].sub(r"\1[REDACTED]", result)
    result = _RAW_SECRET_PATTERNS[1].sub(r"\1[REDACTED]\2", result)
    return result


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def _hash_payload(record: EvidenceRecord, prev_hash: str | None) -> str:
    payload = record.model_dump(mode="json", exclude={"prev_hash", "record_hash"})
    # These fields were added after the current evidence was sealed.  Omitting
    # them when absent keeps historical record hashes verifiable without
    # rewriting or re-sealing the evidence.  New agent records include them
    # when they carry a value, so they remain covered by the hash chain.
    for field in (
        "planned_by",
        "probe_justification",
        "model_proposal",
        "model_interpretation",
    ):
        if payload.get(field) is None:
            payload.pop(field, None)
    payload["prev_hash"] = prev_hash
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


class EvidenceLog:
    """OBSERVED: append-only JSONL evidence with a tamper-evident hash chain."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def _raw_lines(self) -> list[str]:
        if not self.path.exists():
            return []
        return self.path.read_text(encoding="utf-8").splitlines()

    def records(self, verify: bool = True) -> list[EvidenceRecord]:
        records: list[EvidenceRecord] = []
        previous_hash: str | None = None
        for line_number, line in enumerate(self._raw_lines(), start=1):
            if not line.strip():
                continue
            try:
                raw_document = json.loads(line)
            except json.JSONDecodeError as exc:
                raise EvidenceIntegrityError(f"invalid JSON at line {line_number}") from exc
            if not isinstance(raw_document, dict):
                raise EvidenceIntegrityError(f"evidence line {line_number} is not an object")
            if raw_document.get("record_type") == "m0_preflight" and "record_hash" not in raw_document:
                # The first M0 record predates the runtime schema and is intentionally
                # retained verbatim as raw evidence. It is a source record, not a
                # sealed runtime event, so it cannot participate in classification.
                record = EvidenceRecord(
                    record_type="m0_preflight",
                    run_id=str(raw_document.get("run_id", "m0-preflight")),
                    sequence=len(records) + 1,
                    label="OBSERVED",
                    source=str(raw_document.get("source", "local build environment")),
                    outcome="preflight",
                    raw_response=line,
                    metadata={"raw_preflight": raw_document},
                )
                records.append(record)
                continue
            try:
                record = EvidenceRecord.model_validate_json(line)
            except ValidationError as exc:
                raise EvidenceIntegrityError(f"invalid evidence at line {line_number}: {exc}") from exc
            if verify:
                if record.sequence != len(records) + 1:
                    raise EvidenceIntegrityError(f"unexpected sequence at line {line_number}")
                if record.prev_hash != previous_hash:
                    raise EvidenceIntegrityError(f"broken previous hash at line {line_number}")
                expected_hash = _hash_payload(record, previous_hash)
                if record.record_hash != expected_hash:
                    raise EvidenceIntegrityError(f"broken record hash at line {line_number}")
            records.append(record)
            previous_hash = record.record_hash
        return records

    def append(self, record: EvidenceRecord) -> EvidenceRecord:
        records = self.records()
        previous_hash = records[-1].record_hash if records else None
        safe = record.model_copy(
            update={
                "sequence": len(records) + 1,
                "request": redact(record.request),
                "response": redact(record.response),
                "raw_response": redact_raw(record.raw_response),
                "model_proposal": redact(record.model_proposal),
                "model_interpretation": redact(record.model_interpretation),
                "probe_justification": redact_raw(record.probe_justification),
                "prev_hash": previous_hash,
            }
        )
        sealed = safe.model_copy(update={"record_hash": _hash_payload(safe, previous_hash)})
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(sealed.model_dump_json(exclude_none=False) + "\n")
        return sealed

    def extend(self, records: Iterable[EvidenceRecord]) -> list[EvidenceRecord]:
        return [self.append(record) for record in records]
