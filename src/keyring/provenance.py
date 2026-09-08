"""Evidence provenance helpers.

The evidence directory contains more than one account and more than one client.
Facts from those runs must not be reduced to a last-file-wins summary.  This
module gives derived facts a stable, human-readable context without changing
the retained records or their hashes.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

from .models import EvidenceRecord


@dataclass(frozen=True)
class Provenance:
    """The context in which an observation was made."""

    account: str
    client: str
    permission_mode: str

    @property
    def key(self) -> str:
        return "|".join(
            part.strip().lower().replace(" ", "-")
            for part in (self.account, self.client, self.permission_mode)
        )

    def as_dict(self) -> dict[str, str]:
        return {
            "account": self.account,
            "client": self.client,
            "permission_mode": self.permission_mode,
            "key": self.key,
        }


def _source_token(record: EvidenceRecord, filename: str | Path | None) -> str:
    return f"{filename or ''} {record.run_id}".lower()


def _explicit_account(record: EvidenceRecord) -> str | None:
    metadata = record.metadata
    for key in ("account_label", "sub_account_label", "account"):
        value = metadata.get(key)
        if value:
            text = str(value).strip()
            if text:
                return text
    # Account identifiers are not currently stored in the retained records.
    # If a future capture adds one, keep it usable as a stable internal key
    # without publishing the identifier itself in the dashboard.
    for key in ("account_id", "sub_account_id", "subaccount_id"):
        value = metadata.get(key)
        if value:
            digest = sha256(str(value).encode("utf-8")).hexdigest()[:12]
            return f"Account {digest}"
    return None


def account_for(record: EvidenceRecord, filename: str | Path | None = None) -> str:
    explicit = _explicit_account(record)
    if explicit:
        return explicit
    token = _source_token(record, filename)
    if "second-account" in token or "account-b" in token:
        return "Account B"
    if any(
        marker in token
        for marker in ("m0", "full-proof", "client-matrix", "account-a", "run-c")
    ):
        return "Account A"
    return f"Run {record.run_id}"


def _canonical_client(value: Any) -> str | None:
    if not value:
        return None
    text = str(value).strip()
    lowered = text.lower()
    if "claude" in lowered:
        return "Claude Code"
    if "codex" in lowered:
        return "Codex CLI"
    if "gateway" in lowered or "direct" in lowered:
        return "Direct gateway"
    return text


def client_for(record: EvidenceRecord, filename: str | Path | None = None) -> str:
    metadata = record.metadata
    for key in ("client", "client_name"):
        client = _canonical_client(metadata.get(key))
        if client:
            return client
    token = _source_token(record, filename)
    if "second-account" in token:
        return "Codex CLI"
    if "full-proof" in token or "run-c" in token:
        return "Direct gateway"
    return "Client not recorded"


def permission_mode_for(record: EvidenceRecord, filename: str | Path | None = None) -> str:
    raw = record.metadata.get("permission_mode")
    if raw:
        text = str(raw).strip()
        lowered = text.lower()
        if "manual" in lowered:
            return "manual"
        if "default" in lowered or "auto" in lowered:
            return "default"
        return text

    client = client_for(record, filename)
    if record.record_type == "operator_observation" and record.operation == "client_gate_observation":
        return "default"
    if client in {"Claude Code", "Codex CLI"}:
        # The funded and revocation captures were made through the client's
        # ordinary interactive path.  They contain no separate mode override.
        return "default"
    if client == "Direct gateway":
        return "not applicable"
    return "not recorded"


def provenance_for(record: EvidenceRecord, filename: str | Path | None = None) -> Provenance:
    return Provenance(
        account=account_for(record, filename),
        client=client_for(record, filename),
        permission_mode=permission_mode_for(record, filename),
    )


def require_compatible_provenance(
    source: Provenance,
    target: Provenance,
    *,
    source_scope: str = "exact",
) -> Provenance:
    """Reject a fact join whose provenance is not explicitly compatible.

    Most joins require the full account/client/mode key to match.  Account
    balances are the one deliberate exception: they are account-level facts,
    so they may be projected into a client/mode row only when the account still
    matches.  The caller must name that exception explicitly.
    """
    if source_scope == "account":
        if source.account != target.account:
            raise ValueError(
                "refusing to combine facts from different provenance accounts"
            )
        return target
    if source.key != target.key:
        raise ValueError(
            "refusing to combine facts with different provenance keys"
        )
    return target


def is_operator_observation(record: EvidenceRecord) -> bool:
    """Whether a person watched this observation rather than the harness."""
    if record.metadata.get("captured_by_build") is False:
        return True
    evidence_type = str(record.metadata.get("evidence_type", "")).lower()
    return "operator observation" in evidence_type or evidence_type.startswith("operator")


def qualified_label(record: EvidenceRecord, base: str | None = None) -> str:
    """Return the published label with its capture origin when applicable."""
    label = base or str(getattr(record.label, "value", record.label))
    if label != "OBSERVED":
        return label
    return f"OBSERVED · {'operator' if is_operator_observation(record) else 'harness'}"
