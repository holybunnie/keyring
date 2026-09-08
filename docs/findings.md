# KEYRING — findings

These findings are regenerated from the append-only evidence under `evidence/raw/`. The measured client path is Claude Code, using one authenticated Binance Agentic sub-account.

## 1. The measured confirmation path

**OBSERVED:** A deliberately non-executing Spot order probe reached Binance's order-filter validation and returned `-1013 Filter failure: PERCENT_PRICE_BY_SIDE`.

| Path | Gate result | Evidence |
|---|---|---|
| Direct gateway call | No confirmation | `0007-full-proof-probes.jsonl` |
| Claude Code, default mode | No confirmation | `0010-client-matrix.jsonl` |
| Claude Code, manual mode | Prompt shown; operator declined | `0010-client-matrix.jsonl` |

The same Claude Code credential and probe were used in the two client-mode observations. The only changed variable was the permission mode.

**OBSERVED:** The gateway returned a discriminative Binance validation error; the request was not silently accepted as an order.

**DOCUMENTED:** Binance describes trades and transfers as confirmed by the user first. The tested Claude Code default path reached Binance validation without adding that confirmation.

## 2. Scope-filtered authority

**OBSERVED:** The same sub-account produced two measured tool surfaces:

| Grant | Surface |
|---|---|
| `mcp:account:read` | 60 tools, all read operations |
| `mcp:account:read mcp:futures:trade mcp:spot:trade` | 71 tools |

The trade grant added eleven write tools for Spot, USDⓈ-M Futures, and COIN-M Futures. The Account-only grant exposed no order, cancellation, or transfer capability.

**OBSERVED:** The positive control `spot.getAccount` passed in the same session, client, address, and minute as every probe.

| Capability | Probe | Result |
|---|---|---|
| Spot | `spot.newOrder`, `-1013` | **VERIFIED** |
| USDⓈ-M futures | `futures_usds.newOrder`, `-4013` | **VERIFIED** |
| COIN-M futures | `futures_coin.newOrder`, `-1111` | **VERIFIED** |
| Margin | No write tool advertised | **DENIED** at discovery |
| Convert | No write tool advertised | **DENIED** at discovery |
| Transfer | No write tool advertised | **DENIED** at discovery |

All three probes reached parameter validation and were rejected before the matching engine.

## 3. Grant composition is not visible in one permission report

**OBSERVED:** `wallet.getApiKeyPermission` returned the same permission payload under both grants, while the trade grant advertised eleven trading tools and its probes reached order validation.

The effective result is therefore composed from the consent grant, the advertised MCP surface, the positive control, and the controlled invocation—not from the credential report alone.

**OBSERVED:** The consent label **Spot & Margin trading** produced `mcp:spot:trade`; no margin write tool appeared in that surface.

## 4. Least privilege is measurable

**OBSERVED:** The checksummed strategy manifest requires Spot capability for `BTCUSDT` and `ETHUSDT`. The measured grant verified Spot plus both futures product families.

The measured excess is:

- two product families: `coin_m_futures`, `usd_m_futures`;
- eight write tools belonging to those families;
- reconnect and re-authorization required to narrow the grant.

**OBSERVED:** The venue inventory listed 1,362 Spot trading instruments, while the strategy declares 2. The inventory is kept separate from measured authority; only the probed symbol has invocation evidence.

## 5. Zero-state change is proved

**OBSERVED:** Each current probe captured fourteen state components before and after. The snapshots include balances, positions, open orders, and the supporting wallet/product state.

**OBSERVED:** The snapshots were canonicalized, SHA-256 hashed, and chained in append-only evidence. Across the audit:

```text
records replayed        109
state digests seen        6
distinct states           1
identical throughout   True
chain unbroken         True
```

Every digest was identical. A probe with incomplete or changed state proof is discarded by the implementation.

## 6. Financial reach is layered

**OBSERVED:** The measured Agentic sub-account held no capital, no Spot holdings, and no futures positions.

| Layer | Measured value |
|---|---:|
| Capital visible | 0 |
| Capital reachable by verified trading paths | 0 |
| Autonomous capital at risk | 0 |
| Spot holdings | 0 |
| Immediate exit cost | 0 |
| Open futures positions | 0 |

The autonomous-capital value is zero because the account is empty, not because a confirmation gate was observed in the default path.

## 7. Permission changes require reconnection

**OBSERVED:** The Agentic sub-account's View permissions screen listed permissions but offered no edit control. Narrowing the grant required disconnecting and re-authorizing.

The observation is recorded in `evidence/raw/0009-m0-5-permission-mutability.jsonl`, and the scope change between the two grant measurements occurred across that reconnect cycle.

## What problem this solves

KEYRING gives an operator an evidence-backed answer to: **what can this connected Claude Code Agentic session actually reach, what did it attempt, and did the audit change financial state?**

It turns a broad consent label and an ambiguous permission report into a replayable authority map with a proof chain, a least-privilege comparison, and a read-only dashboard.
