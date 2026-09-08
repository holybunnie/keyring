# KEYRING — findings

These findings are regenerated from the append-only evidence under
`evidence/raw/`. The measured client path is Claude Code, using one
authenticated Binance Agentic sub-account.

## 1. Granted is not what Binance reports

**OBSERVED:** `wallet.getApiKeyPermission` returned the same
permission payload under both grants — `enableSpotAndMarginTrading:
false`, `enableFutures: false`, and `enableReading:
true` — while the trade grant advertised eleven trading tools and three
probes reached order validation.

This is an observability gap, not a vulnerability. The cause remains
**ASSUMED**; the finding is the measured disagreement between the credential
report and the session surface plus invocation result.

## 2. Granted is not what the consent screen says

**OBSERVED:** The toggle labelled **Spot & Margin trading** produced
`mcp:spot:trade`, and no margin write tool appeared. The label
over-states what it grants; enforcement was not shown to be weak.

## 3. Protection is the client's, not Binance's

**OBSERVED:** The Spot `LIMIT BUY` probe for
`0.00001` BTC at `0.01` USDT reached
`-1013 Filter failure: PERCENT_PRICE_BY_SIDE`.

| Path | Gate result | Evidence |
|---|---|---|
| Direct gateway | No confirmation | `0007-full-proof-probes.jsonl` |
| Claude Code, default mode | No confirmation | `0010-client-matrix.jsonl` |
| Claude Code, manual mode | Prompt shown; operator declined | `0010-client-matrix.jsonl` |

**DOCUMENTED:** Binance describes trades and transfers as confirmed by the
user first. The tested Claude Code default path reached Binance validation
without adding that confirmation.

## 4. Enforcement behaved as documented

**OBSERVED:** The account-only grant advertised 60 read tools. The selected
grant advertised 71 tools, including eleven writes. Spot, USDⓈ-M Futures, and
COIN-M Futures probes returned parameter-rejection codes and retained identical
state proofs. Margin, Convert, and Transfer had no write tool advertised and
were **DENIED** at discovery.

| Capability | Probe | Result |
|---|---|---|
| Spot | `spot.newOrder`, `-1013` | **VERIFIED** |
| USDⓈ-M futures | `futures_usds.newOrder`, `-4013` | **VERIFIED** |
| COIN-M futures | `futures_coin.newOrder`, `-1111` | **VERIFIED** |

## 5. Effective authority, least privilege, and financial reach

**OBSERVED:** The strategy needs Spot for `BTCUSDT` and
`ETHUSDT`. The measured grant also verified both futures families:
measured excess is `coin_m_futures` and
`usd_m_futures`, with eight excess write tools. Narrowing requires
disconnecting and re-authorizing.

**OBSERVED:** The venue lists 1,362 spot instruments while the strategy
declares 2. That inventory is a potential surface only and is not merged with
measured authority.

**OBSERVED:** The measured sub-account was empty: capital visible, verified
trading reach, autonomous capital at risk, Spot holdings, immediate exit cost,
and open futures positions were all 0.

## 6. Zero-state proof

**OBSERVED:** Each current probe captured fourteen state components before and
after. The evidence chain replayed as:

```text
records replayed        109
state digests seen        6
distinct states           1
identical throughout   True
chain unbroken         True
```

Every digest was identical. Incomplete or changed state proof discards a probe.
