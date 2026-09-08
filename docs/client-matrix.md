# Claude Code measurement

This build measures one authenticated Binance Agentic sub-account through
Claude Code. The direct gateway call is the baseline; the two client rows use
the same credential and the same controlled Spot probe.

## Controlled probe

The probe was a Spot LIMIT BUY for 0.00001 BTC at 0.01 USDT on BTCUSDT. Binance
rejected it at order-filter validation with -1013 Filter failure:
PERCENT_PRICE_BY_SIDE, before the matching engine.

## Measured paths

| Path | Configuration | Grant | Probe result | Gate | Evidence |
|---|---|---|---|---|---|
| Direct gateway | Valid session token | mcp:account:read mcp:futures:trade mcp:spot:trade | -1013 | **NONE** | 0007-full-proof-probes.jsonl |
| Claude Code | Default permission mode | Same grant | -1013 | **NONE** | 0010-client-matrix.jsonl |
| Claude Code | manual permission mode | Same grant | No call after decline | **CLIENT PROMPT** | 0010-client-matrix.jsonl |

**OBSERVED:** The Claude Code default run had no project allowedTools entries
or defaultMode override. Manual mode displayed a prompt before the same
invocation; the operator declined it.

## Authority context

The same credential produced two scope-filtered surfaces:

| Grant | Tools |
|---|---:|
| mcp:account:read | 60 |
| mcp:account:read mcp:futures:trade mcp:spot:trade | 71 |

The trade grant added eleven write tools. The positive control spot.getAccount
passed in the same session used by the probes.

## Conclusion

**OBSERVED:** In the measured Claude Code path, the gateway did not add a
confirmation. Claude Code default mode added none; manual mode added a client
prompt.
