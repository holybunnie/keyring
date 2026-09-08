# KEYRING verification

This document describes the retained measurement, how the published results
are derived, and the limits of replay. It contains no live credentials and no
step requires reconnecting a Binance account.

## What was measured

KEYRING compared four authority surfaces across two authenticated Binance
Agentic sub-accounts:

1. the MCP scopes selected during authorization;
2. Binance's permission self-report;
3. the runtime tool schemas exposed to the connected client; and
4. controlled trading-shaped requests designed to stop at Binance parameter
   validation before execution.

Both selected grants exposed 71 tools, including 11 trading writes. On both
accounts, controlled tests reached validation for Spot, USDⓈ-M Futures, and
COIN-M Futures. Binance's permission self-report described Spot and Futures as
disabled on Account A and enabled on Account B. This is reported as an
observability gap, not a vulnerability.

## How results are derived

Every active JSONL file is parsed into the typed evidence schema and its
per-file hash chain is verified before it contributes to a result. The
`authority`, `trace`, `least-privilege`, `financial-reach`, `agent-replay`, and
dashboard views are derived from those verified records.

Every controlled capability test includes a same-session connection check,
complete account state before the request, one budgeted request, and complete
account state afterward. A test is discarded if the state capture is
incomplete or changes.

Operator-observed client behavior remains labelled `OBSERVED · operator`.
Harness-captured requests and responses remain labelled `OBSERVED · harness`.
Confirmation and capital findings remain keyed by account, client, permission
mode, and source.

## Replay

From a clean Python 3.11 or newer virtual environment:

```bash
pip install -e ".[dev]"
python -m keyring agent-replay
python -m keyring dashboard
```

`agent-replay` defaults to `0012-codex-cli-second-account.jsonl#78`. It shows
the retained runtime schema and filters, recorded model proposal, recomputed
deterministic non-execution gate, controlled request, Binance response, model
interpretation, retained deterministic decision, and before/after state proof.
It performs no network or model call and writes nothing.

The local dashboard derives its state from `evidence/raw/` at startup. The
production service uses a deterministic artifact made by
`build-dashboard-state`; the server verifies its digest and complete source
manifest before serving it. The builder refuses evidence that fails validation
or hash verification.

## Evidence references

- Account A grant, runtime surface, permission report, and probes:
  `evidence/raw/0005-m0-run-b.jsonl`,
  `evidence/raw/0007-full-proof-probes.jsonl`, and
  `evidence/raw/0008-run-c-coinm.jsonl`.
- Client comparison: `evidence/raw/0010-client-matrix.jsonl`.
- Account B grant, runtime surface, permission report, probes, and agent record:
  `evidence/raw/0012-codex-cli-second-account.jsonl`.
- Funded capital measurement:
  `evidence/raw/0013-codex-cli-funded-financial-reach.jsonl` and
  `evidence/raw/0015-codex-cli-second-account-exit-cost-20260908.jsonl`.
- Revocation observation:
  `evidence/raw/0017-codex-cli-second-account-revocation-20260908.jsonl`.

## Known limitations

- Replaying the retained run reproduces analysis, not the original authenticated
  capture.
- Whether Binance inserts a server-side confirmation after successful
  validation and before execution was not measured.
- Futures leverage brackets, margin mode, and account limits were not resolved,
  so no futures gross-notional ceiling is asserted.
- The cause of the different permission self-reports was not established.
- Hash chains demonstrate internal consistency. They do not provide an external
  timestamp, signature, authorship proof, or protection against full resealing.
- Historical `egress_country` fields describe measurement infrastructure only.
  Future records include this field only when `KEYRING_EGRESS_COUNTRY` is
  explicitly supplied; it is not participant eligibility evidence.

## Automated verification

The GitHub Actions workflow installs the development environment and runs:

```text
compile → mypy → Bandit → pytest
```

Published-number tests ensure that headline authority, provenance-specific
financial results, and replay behavior continue to match the retained evidence.
