# KEYRING

> Binance shows you what you authorized. KEYRING measures what that authorization can actually do.

> No exploits. No transactions. No guessing. Just measured authority.

## Problem

An Agentic grant is not the same thing as effective authority. The consent screen shows a grant category, while the gateway advertises a tool surface and the client decides whether to ask for confirmation. A credential self-report can also disagree with the scope actually used by the session.

KEYRING closes that evidence gap for one authenticated Binance Agentic sub-account measured through Claude Code. It joins the grant, advertised tools, a controlled invocation, client gate observation, and before/after financial state into one reproducible record.

## What we built

KEYRING is a Python audit and replay tool with five layers:

1. **Discovery:** capture the authenticated MCP surface and granted scope.
2. **Authority measurement:** run a positive read control and one deliberately non-executing probe per capability.
3. **State proof:** capture balances, positions, and open orders before and after each probe, then hash-chain the evidence.
4. **Analysis:** derive effective authority, least-privilege excess, and layered financial reach from the log.
5. **Presentation:** serve a read-only dashboard with expandable proof traces.

The transport refuses write-shaped calls through the ordinary read path. Probe calls are explicit, budgeted, rate-limited, and stopped on unsafe gateway responses. KEYRING has no state-changing write path.

Every claim in this document is labelled **OBSERVED** (run and recorded) or **DOCUMENTED** (stated by a first-party Binance source).

## Results

### Confirmation in the measured Claude Code path

**OBSERVED:** A spot `LIMIT BUY` for `0.00001` BTC at `0.01` USDT reached Binance order-filter validation and returned `-1013 Filter failure: PERCENT_PRICE_BY_SIDE` without a confirmation in the direct gateway path or Claude Code's default mode.

| Path | Confirmation | Evidence |
|---|---|---|
| Direct gateway call with a valid session token | **none** | `evidence/raw/0007-full-proof-probes.jsonl` |
| Claude Code, default permission mode | **none** | `evidence/raw/0010-client-matrix.jsonl` |
| Claude Code, `--permission-mode manual` | **prompted; operator declined** | `evidence/raw/0010-client-matrix.jsonl` |

**OBSERVED:** The Claude Code default run had no project `allowedTools` entries or `defaultMode` override. Manual mode changed the client gate while the credential and probe stayed the same.

**DOCUMENTED:** Binance describes every trade or transfer as confirmed by the user first. The measured Claude Code default path did not add that confirmation before the request reached Binance validation.

### Scope-filtered authority

**OBSERVED:** The same Agentic sub-account was measured under two grants.

| Grant | Advertised tools |
|---|---:|
| `mcp:account:read` | 60, all read operations |
| `mcp:account:read mcp:futures:trade mcp:spot:trade` | 71 |

**OBSERVED:** The second grant added eleven write tools for Spot, USDⓈ-M Futures, and COIN-M Futures. The Account-only grant advertised no order creation, amendment, cancellation, or transfer capability.

**OBSERVED:** The positive control, `spot.getAccount`, passed in the same session, client, address, and minute as every probe.

| Capability | Advertised writes | Probe | Code | State | Result |
|---|---:|---|---|---|---|
| Spot | 3 | `spot.newOrder` | `-1013` | IDENTICAL | **VERIFIED** |
| USDⓈ-M futures | 4 | `futures_usds.newOrder` | `-4013` | IDENTICAL | **VERIFIED** |
| COIN-M futures | 4 | `futures_coin.newOrder` | `-1111` | IDENTICAL | **VERIFIED** |
| Margin | 0 | — | — | — | **DENIED** at discovery |
| Convert | 0 | — | — | — | **DENIED** at discovery |
| Transfer | 0 | — | — | — | **DENIED** at discovery |

### Grant composition

**OBSERVED:** `wallet.getApiKeyPermission` returned the same permission payload under both grants, while the trade grant advertised eleven trading tools and the three probes reached order validation. Effective authority therefore has to be measured from the session surface and invocation result, not read from one credential report.

**OBSERVED:** The consent label **Spot & Margin trading** produced `mcp:spot:trade`; no margin write tool appeared in the resulting surface.

### Least-privilege diff

**OBSERVED:** The checksummed strategy manifest declares Spot capability for `BTCUSDT` and `ETHUSDT`. The measured grant also verified the two futures product families.

```text
LEAST-PRIVILEGE DIFF — example-spot-strategy
  granted scope   mcp:account:read mcp:futures:trade mcp:spot:trade

NEEDED       (declared in the manifest)
  capabilities   spot
  instruments    2  (BTCUSDT, ETHUSDT)

EFFECTIVE    (verified by probe and state proof)
  capabilities   coin_m_futures, spot, usd_m_futures

EXCESS — MEASURED
  capabilities   coin_m_futures, usd_m_futures
  write tools    8

REMEDIATION COST
  RECONNECT_REQUIRED
  The grant must be disconnected and re-authorized to narrow it.
```

**OBSERVED:** The venue lists 1,362 spot instruments trading; the strategy declares 2. The measured authority result is based on the probed symbol, while the venue listing remains a separate inventory figure.

### Financial reach

**OBSERVED:** The measured Agentic sub-account was empty.

```text
FINANCIAL REACH, LAYERED

  Capital visible                                  0
  Capital reachable by trading                     0
  Autonomous capital at risk                       0
  Spot holdings (non-zero assets)                  0
  Immediate exit cost                              0
  Open futures positions                            0

  capabilities verified        coin_m_futures, spot, usd_m_futures
  spot symbols probed          1
  spot symbols listed trading  1362
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

**OBSERVED:** Every state digest in the audit is identical. A probe with incomplete or changed state proof is discarded by the implementation.

## Reproduce it

Every result is regenerated from the evidence log; nothing is hand-entered.

```bash
pip install -e .
python -m keyring authority          # rebuild effective authority
python -m keyring least-privilege    # compare the manifest with the grant
python -m keyring financial-reach    # show layered capital reach
python -m keyring validate-config    # verify configuration checksums
python -m keyring dashboard          # serve the read-only dashboard
python -m pytest -q                  # run the test suite
```

Raw responses are in [`evidence/raw/`](evidence/raw/), hash-chained with credential-shaped values redacted. The measured record is in [`docs/m0.md`](docs/m0.md); the findings are in [`docs/findings.md`](docs/findings.md).

## Scope

**OBSERVED:** This build reports the captured Claude Code default and manual permission modes for the measured Agentic sub-account. The direct gateway path is the baseline used to identify gateway behavior.

**DOCUMENTED:** Binance security guidance says not to paste the MCP endpoint into an AI chat or open it directly in a browser. The build follows that guidance.

**OBSERVED:** Rate limiting is enforced in code: a hard probe budget, per-minute pacing, `429` backoff, immediate `418` stop, `403` halt, and no aggressive retry after a server failure.
