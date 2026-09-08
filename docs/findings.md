# KEYRING — findings

These findings are regenerated from the append-only evidence under
`evidence/raw/`. The current measurement covers the original Claude Code
sub-account and a second sub-account authorized through Codex CLI.

## 1. The permission self-report diverged by sub-account

**OBSERVED:** On the original account, `wallet.getApiKeyPermission` returned
`enableSpotAndMarginTrading: false`, `enableFutures: false`, and
`enableReading: true` under both measured grants. The trade-grant surface
advertised eleven writes and three controlled probes reached order validation.

**OBSERVED:** On the second account, the same endpoint returned
`enableSpotAndMarginTrading: true`, `enableFutures: true`, `enableMargin: false`,
and `enableReading: true` while the selected grant again exposed 71 tools and
eleven writes.

This is an observability gap, not a vulnerability. The measured result is that
the credential self-report did not describe authority consistently across the
two sub-accounts. The cause remains **ASSUMED**; the finding does not depend on
explaining it.

## 2. The consent label and effective surface diverged

**OBSERVED:** The toggle labelled **Spot & Margin trading** produced
`mcp:spot:trade`, and no margin write tool appeared under that grant.

**NOT MEASURED:** Whether the measured account was margin-eligible. The
divergence may reflect the label, account eligibility, sub-account
configuration, or a combination. Enforcement was not shown to be weak.

## 3. Confirmation before validation was client-dependent

**OBSERVED:** A deliberately non-executing Spot `LIMIT BUY` reached Binance
filter validation with `-1013 Filter failure: PERCENT_PRICE_BY_SIDE` by direct
gateway call and through Claude Code default mode. Claude Code manual mode
displayed a prompt and the operator declined. Codex CLI default mode displayed
a prompt before its compact MCP dispatcher stopped on a tool-name error, before
Binance validation.

| Path | Gate result | Evidence |
|---|---|---|
| Direct gateway | No confirmation | `0007-full-proof-probes.jsonl` |
| Claude Code, default mode | No confirmation | `0010-client-matrix.jsonl` |
| Claude Code, manual mode | Prompt shown; operator declined | `0010-client-matrix.jsonl` |
| Codex CLI, default mode | Prompt shown; dispatcher stopped before Binance | `0012-codex-cli-second-account.jsonl#141` |

**DOCUMENTED:** Binance describes trades and transfers as confirmed by the user
first.

**NOT MEASURED:** Whether a server-side confirmation exists after successful
validation and before execution. No valid order was allowed to reach execution,
so no claim is made about that step.

## 4. Enforcement behaved as measured

**OBSERVED:** Both selected-grant surfaces advertised 71 tools, including
eleven writes. All three product paths in both capability runs reached
parameter-rejection responses while each probe's complete before/after state
proof remained identical.

| Capability | Original result | Second-account result |
|---|---|---|
| Spot | `spot.newOrder`, `-1013` | `spot.newOrder`, `-1100` |
| USDⓈ-M futures | `futures_usds.newOrder`, `-4013` | `futures_usds.newOrder`, `-4013` |
| COIN-M futures | `futures_coin.newOrder`, `-1111` | `futures_coin.newOrder`, `-4013` |

**OBSERVED:** Margin, Convert, and Transfer exposed no write tool in the
selected surface and were classified **DENIED** at discovery. The second-run
Spot `-1100` was a malformed numeric-parameter rejection from the first model
proposal; it was still before execution and is now a deterministic known
parameter-rejection class. New model numeric arguments are normalized before
dispatch.

## 5. Effective authority, least privilege, and financial reach

**OBSERVED:** The strategy needs Spot for `BTCUSDT` and `ETHUSDT`. The measured
grant also verified both futures families, producing measured excess of
`coin_m_futures` and `usd_m_futures`, with eight excess write tools. Narrowing
requires disconnecting and re-authorizing.

**OBSERVED:** The venue lists 1,362 spot instruments while the strategy declares
two. That inventory is a potential surface only and is not merged with measured
authority.

**OBSERVED:** Both capability sub-accounts were empty. Current financial reach
therefore reports zero visible capital, zero verified trading reach, zero
autonomous capital at risk, zero Spot holdings, zero immediate exit cost, and
zero open futures positions. The zero exit cost is by absence of holdings, not
by an order-book walk.

**OBSERVED:** The zero autonomous-capital figure is a consequence of the empty
accounts; Codex CLI default mode displayed a client prompt, while Claude Code
default mode did not.

## 6. Zero-state proof

**OBSERVED:** Every current probe captured fourteen state components before and
after. The complete evidence set currently replays as:

```text
records replayed        250
state digests seen       14
distinct states           3
identical throughout   False
probe pairs identical   True
chain unbroken         True
```

**OBSERVED:** Every completed before/after pair is identical and every evidence
file replays with an unbroken record chain. The aggregate contains independent
account sessions, and optional wallet metadata changed between captures, so a
single aggregate snapshot state is not asserted.
