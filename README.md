# KEYRING

> Binance shows you what you authorized. KEYRING measures what that authorization can actually do.

> No exploits. No transactions. No guessing. Just measured authority.

## Findings

### Granted is not what Binance reports

**OBSERVED:** `wallet.getApiKeyPermission` returned the same payload under both measured grants: `enableSpotAndMarginTrading: false`, `enableFutures: false`, and `enableReading: true`. At the same time, the trade-grant surface advertised eleven trading tools and three controlled probes reached Binance order validation.

This is an observability gap, not a vulnerability. The endpoint an operator would query to audit the session describes authority differently from the session surface and invocation result. The cause remains **ASSUMED**; the finding does not depend on explaining it.

### Granted is not what the consent screen says

**OBSERVED:** The consent toggle labelled **Spot & Margin trading** produced `mcp:spot:trade`, and no margin write tool appeared under that grant. The label over-states what it grants; enforcement was not shown to be weak.

### Protection is the client's, not Binance's

**OBSERVED:** A deliberately non-executing Spot `LIMIT BUY` for `0.00001` BTC at `0.01` USDT reached Binance filter validation with `-1013 Filter failure: PERCENT_PRICE_BY_SIDE`.

| Path | Confirmation | Evidence |
|---|---|---|
| Direct gateway call | none | `evidence/raw/0007-full-proof-probes.jsonl` |
| Claude Code, default permission mode | none | `evidence/raw/0010-client-matrix.jsonl` |
| Claude Code, manual permission mode | prompt shown; operator declined | `evidence/raw/0010-client-matrix.jsonl` |

**DOCUMENTED:** Binance describes every trade or transfer as confirmed by the user first. The measured Claude Code default path reached Binance validation without adding that confirmation.

### Enforcement behaved as documented

**OBSERVED:** The selected grant exposed eleven write tools, and each of the three measured product probes reached a parameter-rejection response while its complete before/after state proof remained identical.

| Capability | Advertised writes | Probe | Code | Result |
|---|---:|---|---|---|
| Spot | 3 | `spot.newOrder` | `-1013` | **VERIFIED** |
| USDⓈ-M futures | 4 | `futures_usds.newOrder` | `-4013` | **VERIFIED** |
| COIN-M futures | 4 | `futures_coin.newOrder` | `-1111` | **VERIFIED** |
| Margin | 0 | — | — | **DENIED** at discovery |
| Convert | 0 | — | — | **DENIED** at discovery |
| Transfer | 0 | — | — | **DENIED** at discovery |

**OBSERVED:** The account-only grant advertised 60 read tools. The selected grant advertised 71 tools, adding eleven write tools for Spot, USDⓈ-M Futures, and COIN-M Futures. The positive control `spot.getAccount` passed in the same session, client, address, and minute as each probe.

### Effective authority and least privilege

**OBSERVED:** The same authenticated sub-account was measured under:

| Grant | Surface |
|---|---:|
| `mcp:account:read` | 60 tools |
| `mcp:account:read mcp:futures:trade mcp:spot:trade` | 71 tools |

**OBSERVED:** The checksummed strategy manifest needs Spot for `BTCUSDT` and `ETHUSDT`. The measured grant also verified both futures product families, producing measured excess of `coin_m_futures` and `usd_m_futures` and eight measured excess write tools. Narrowing requires disconnecting and re-authorizing.

**OBSERVED:** The venue lists 1,362 spot instruments trading; the strategy declares 2. The venue inventory is a potential surface only and is never added to measured authority.

### Financial reach

**OBSERVED:** The measured Agentic sub-account was empty.

```text
Capital visible                                  0
Capital reachable by verified trading paths     0
Autonomous capital at risk                       0
Spot holdings                                    0
Immediate exit cost                              0
Open futures positions                           0
```

**OBSERVED:** The zero autonomous-capital figure reflects the empty account. It is not evidence of a confirmation gate.

### Zero-state proof

**OBSERVED:** Every current probe captures fourteen state components before and after. Each snapshot is canonicalized, SHA-256 hashed, and linked into the append-only evidence chain.

```text
records replayed        109
state digests seen        6
distinct states           1
identical throughout   True
chain unbroken         True
```

**OBSERVED:** Every current state digest is identical. A probe with incomplete or changed state proof is discarded.

## What problem this solves

An Agentic consent grant, a gateway tool surface, a client confirmation policy, and a credential self-report are different evidence surfaces. KEYRING joins them into one replayable answer to: **what can this connected session actually reach, what did it attempt, and did the audit change financial state?**

The result is an evidence-derived authority map, proof trace, least-privilege comparison, layered financial-reach view, and read-only dashboard. It detects disagreements between first-party surfaces without calling those disagreements exploits.

## What we built

- Runtime MCP discovery with raw responses and granted-scope evidence.
- A positive control and one budgeted, deliberately non-executing probe per measured capability.
- Complete before/after financial snapshots with canonical digests and append-only hash chains.
- Deterministic authority classification, least-privilege diff, and layered financial reach.
- Permission traces in which every classification line resolves to evidence.
- A read-only dashboard rebuilt from the current classifier path.
- A narrow Claude boundary: proposal planning and unmatched-response interpretation only.

## Model boundary

**OBSERVED:** KEYRING uses Claude in exactly two places: proposing probe arguments against schemas discovered at runtime, and interpreting gateway responses that no deterministic matcher recognises. In both cases the model **proposes**; deterministic code decides. No classification, no published number, no financial figure and no verdict in this repository is produced by a model. Every probe proposal is validated against the symbol's live filters before it is sent, and rejected if it could execute. Probe records carry `planned_by` and a justification; model-assisted classifications record both the proposal and the classifier's decision, including disagreements.

The historical evidence remains unchanged. Its older probe records are shown as planning fields not recorded, rather than falsely labelled as model output.

## Reproduce it

All analysis is regenerated from the evidence log; nothing is hand-entered.

```bash
pip install -e .
python -m keyring authority
python -m keyring trace
python -m keyring least-privilege
python -m keyring financial-reach
python -m keyring validate-config
python -m keyring dashboard
python -m pytest -q
```

For an externally reachable demo, bind the read-only server explicitly:

```bash
python -m keyring dashboard --host 0.0.0.0 --port 8080
```

Model-assisted planning uses the `keyring plan-probe` subcommand with a discovered tool schema and live filters. Set `ANTHROPIC_API_KEY` and an explicit `KEYRING_MODEL` only when choosing that path. The `keyring interpret-response` subcommand is similarly optional and only sends unmatched responses to Claude for a proposal.

Raw responses are in [`evidence/raw/`](evidence/raw/), with credential-shaped values redacted. The measured method is in [`docs/m0.md`](docs/m0.md); the findings are in [`docs/findings.md`](docs/findings.md).

## Scope

**OBSERVED:** The current evidence measures one authenticated Binance Agentic sub-account through Claude Code and a direct gateway baseline.

**DOCUMENTED:** Binance security guidance says not to paste the MCP endpoint into an AI chat or open it directly in a browser. The build follows that guidance.

**OBSERVED:** Rate limiting is enforced in code: a hard probe budget, per-minute pacing, `429` backoff, immediate `418` stop, `403` halt, and no aggressive retry after a server failure.
