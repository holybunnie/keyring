# Superseded evidence

**OBSERVED:** Records here no longer verify against the current `EvidenceRecord`
schema, or have been replaced by a stronger record of the same observation. They
are retained rather than deleted so the audit trail stays complete.

Nothing in this directory is used to derive a classification.

## 0006-m0-3-probe.jsonl

**OBSERVED:** This is the first `spot.newOrder` probe. Its response — `-1013`,
`Filter failure: PERCENT_PRICE_BY_SIDE` — is the same observation later recorded
under a complete state proof in `evidence/raw/0007-full-proof-probes.jsonl`.

**OBSERVED:** Two things invalidated it. Its Law 3 state proof was incomplete:
spot balances and spot open orders were captured, futures positions were not.
And `StateSnapshot` subsequently gained `components` and `missing` fields, which
changed the canonical record hash, so the record no longer passes chain
verification.

**OBSERVED:** The record hash was NOT recomputed to make it pass. A chain that
can be rewritten to fit proves nothing.
