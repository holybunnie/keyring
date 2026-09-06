**OBSERVED (local repository behavior):** KEYRING performs zero-state-change auditing. It cannot trade, transfer or revoke. It audits one Binance account using that account's own grants, and every capability probe is constructed to terminate before execution, with balances, positions and open orders verified unchanged before and after. Probing is rate-limited by design and runs at one probe per capability. **DOCUMENTED (Binance security guidance):** the MCP endpoint is never pasted into an AI chat and never opened in a browser.

# KEYRING

**ASSUMED (product thesis):** Binance shows you what you authorized. KEYRING measures what that authorization can actually do.

**ASSUMED (product boundary):** No exploits. No transactions. No guessing. Just measured authority.

## First-party contradictions

**DOCUMENTED:** The following first-party Binance sources describe the same controls differently. **INCONCLUSIVE:** the measured column is unresolved until a live record is appended.

| Question | Source A | Source B | KEYRING measures | Measured |
|---|---|---|---|---|
| Can permissions be narrowed in place? | **DOCUMENTED:** [MCP documentation](https://developers.binance.com/en/docs/agent-native/mcp-server/agentic) says disconnect and reconnect to update. | **DOCUMENTED:** [Binance Agent OS launch blog](https://www.binance.com/en/blog/ecosystem/5991233187660196794) says permissions can be reviewed or changed under Account Management. | **OBSERVED procedure:** attempt an in-place change. | **INCONCLUSIVE:** no authenticated session. |
| Is confirmation always required? | **DOCUMENTED:** [MCP documentation](https://developers.binance.com/en/docs/agent-native/mcp-server/agentic) says every non-read action uses confirmation. | **DOCUMENTED:** [Binance Support](https://www.binance.com/en/support/faq/detail/7a6e676e36fb455d96478932cb12d9f3) says flows are designed to request confirmation before consequential actions. | **OBSERVED procedure:** map whether the gate is client-side, server-side, or absent. | **INCONCLUSIVE:** no authenticated session. |
| Does autonomous execution exist? | **DOCUMENTED:** [Binance Academy](https://www.binance.com/en/academy/articles/how-binance-agent-os-is-changing-crypto-trading) describes per-order approval or autonomous trading. | **DOCUMENTED:** [MCP documentation](https://developers.binance.com/en/docs/agent-native/mcp-server/agentic) does not mention an autonomous mode. | **OBSERVED procedure:** record whether an invocation reaches Binance without a human click. | **INCONCLUSIVE:** no authenticated session. |
| What does Emergency Stop do? | **DOCUMENTED:** [MCP documentation](https://developers.binance.com/en/docs/agent-native/mcp-server/agentic) describes disconnecting agents and cancelling spot, margin, and futures positions and orders. | **DOCUMENTED:** [Binance Support](https://www.binance.com/en/support/faq/detail/7a6e676e36fb455d96478932cb12d9f3) says behavior can vary by product. | **ASSUMED boundary:** KEYRING does not trigger Emergency Stop. | **DOCUMENTED disagreement:** no trigger attempted. |

## Current result

**OBSERVED:** The repository contains a local M0 preflight record, but no authenticated Binance Agentic session was available when it was captured. The raw record is published in [`docs/m0.md`](docs/m0.md) and [`evidence/raw/0001-m0-preflight.jsonl`](evidence/raw/0001-m0-preflight.jsonl).

**INCONCLUSIVE:** `tools/list`, the Account positive control, the non-executing action, the Account/Trade differential, and in-place permission mutability have not been observed in a live session. The dashboard therefore stays in degraded mode and does not present effective authority as measured.

## What exists in this repository

**OBSERVED:** `src/keyring/evidence.py` appends validated JSONL records with sequence numbers and a hash chain. It redacts credential-shaped fields before writing.

**OBSERVED:** `src/keyring/classifier.py` derives `VERIFIED`, `DENIED`, `ADVERTISED_ONLY`, or `INCONCLUSIVE` from evidence. Classifications are not stored as user-editable state.

**OBSERVED:** `src/keyring/safety.py` requires a passing Account positive control, enforces one probe per capability and hard run/minute budgets, records before/after state for every probe attempt, honors `Retry-After`, halts on `418`/`403`, and leaves `5xx` inconclusive.

**OBSERVED:** `src/keyring/reach.py` separates measured symbols from potential/documented symbols. A venue listing is never labelled effective authority by itself.

**OBSERVED:** `src/keyring/dashboard.py` serves only `GET /` and `GET /api/state`; its `POST` path returns `405`. It renders labels and proof-derived reasons beside classifications.

**ASSUMED:** The exact Agentic JSON-RPC envelope and tool names are unresolved until an authenticated `tools/list` response is captured. The generic transport in `src/keyring/agentic.py` does not invent them.

## Run locally

```bash
python -m pip install -e '.[dev]'
python -m keyring validate-config
python -m keyring classify
python -m keyring dashboard --host 127.0.0.1 --port 8080
```

**OBSERVED:** The current `classify` command returns no effective capability rows because the committed evidence contains only the unauthenticated preflight. That is the expected degraded result, not a successful authority measurement.

**ASSUMED:** Binding the dashboard to `0.0.0.0` and deploying it would make it reachable outside the build machine; deployment is not present in this repository yet.

## Evidence discipline

**OBSERVED:** Raw evidence is documented in [`docs/evidence-format.md`](docs/evidence-format.md). A record that cannot prove unchanged balances, positions, and open orders is not eligible for a positive classification.

**DOCUMENTED:** Binance Spot API error `-2015` conflates invalid API-key, IP, and permission failures. **OBSERVED implementation rule:** KEYRING never treats it as a permission result without a passing positive control.

**DOCUMENTED:** Binance Spot API `-1013` represents a request rejected before the Matching Engine, including filter failures. **ASSUMED until M0:** whether that error survives the Agentic MCP layer unchanged.

**DOCUMENTED:** HTTP `429` requires backoff and `Retry-After`; continuing after `429` can lead to `418`. **OBSERVED implementation rule:** `418` and `403` stop the runner immediately, and `5xx` remains `INCONCLUSIVE`.

**DOCUMENTED:** Binance instructs users not to paste the MCP endpoint into an AI chat to install it and not to open the endpoint directly in a browser. KEYRING follows that instruction; a live session must be supplied through the supported client/session path, never by exposing endpoint material in evidence.

## Limits

**INCONCLUSIVE:** No live gateway response is included in this public repository yet. There is no claim here about scope-dependent tool surfaces, error-code preservation, authorization ordering, confirmation placement, self-built client acceptance, or an Agent OS `order.test` equivalent.

**ASSUMED:** The strategy manifest in [`config/strategy.yaml`](config/strategy.yaml) is an example requirement set supplied by the operator. It is not a Binance grant and it is not inferred from a model.

**OBSERVED:** The project intentionally publishes ignorance. The preflight record is evidence that the local build had no configured session; it is not evidence that Binance denied or allowed any capability.
