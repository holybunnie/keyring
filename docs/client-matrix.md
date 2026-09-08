# Client matrix measurement

The matrix now contains the original Claude Code measurement and the second
account's Codex CLI observation. Both capability runs used the same selected
grant: `mcp:account:read mcp:futures:trade mcp:spot:trade`.

## Controlled probe

The controlled Spot probe was a `LIMIT BUY` for `0.00001000` BTC at `1.00`
USDT on BTCUSDT. Its notional was below the live minimum-notional filter, so
it was designed to stop before execution.

## Measured paths

| Path | Configuration | Result | Gate | Evidence |
|---|---|---|---|---|
| Direct gateway, original account | Valid session token | `-1013` filter rejection | **NONE** | `0007-full-proof-probes.jsonl` |
| Claude Code, original account | Default permission mode | `-1013` filter rejection | **NONE** | `0010-client-matrix.jsonl` |
| Claude Code, original account | Manual permission mode | No call after decline | **CLIENT PROMPT** | `0010-client-matrix.jsonl` |
| Codex CLI, second account | Default interactive settings | MCP dispatcher stopped before Binance validation | **CLIENT PROMPT** | `0012-codex-cli-second-account.jsonl#141` |

**OBSERVED:** Claude Code default mode had no project `allowedTools` entries or
`defaultMode` override. Codex CLI default mode was run without approval or
sandbox overrides. Its confirmation prompt appeared before the MCP call; after
the operator allowed the one safe probe, the compact dispatcher generated
`create_spot_newOrder`, which the server rejected before the request reached
Binance validation. The client-gate result is therefore recorded, while no
Codex exchange response is used as a capability result.

## Authority context

| Account/run | Account-only surface | Selected-grant surface | Selected-grant writes |
|---|---:|---:|---:|
| Original account | 60 tools | 71 tools | 11 |
| Second account | 60 tools | 71 tools | 11 |

**OBSERVED:** The two selected-grant surfaces contained the same eleven write
tools across Spot, USDⓈ-M Futures, and COIN-M Futures. The positive control
`spot.getAccount` passed in the second capability run before each probe.

## Permission self-report comparison

**OBSERVED:** The original account's `wallet.getApiKeyPermission` report had
`enableSpotAndMarginTrading: false` and `enableFutures: false`, while the
second account's report had both values `true` and `enableMargin: false`. The
same endpoint therefore produced different authority descriptions across the
two sub-accounts.

## Conclusion

**OBSERVED:** The tested client defaults did not behave identically. Claude Code
default mode reached the gateway without a confirmation; Codex CLI default mode
displayed a client confirmation before its MCP dispatcher failed before
Binance validation. Claude Code manual mode also displayed a prompt and the
operator declined it.
