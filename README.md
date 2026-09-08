# KEYRING

> Binance shows you what you authorized. KEYRING measures what that authorization can actually do.

> No exploits. No transactions. No guessing. Just measured authority.

## Results

### The permission self-report diverged by sub-account

**OBSERVED:** On the original Claude Code sub-account, `wallet.getApiKeyPermission` returned `enableSpotAndMarginTrading: false`, `enableFutures: false`, and `enableReading: true` under both measured grants. At the same time, the trade-grant surface advertised eleven trading tools and three controlled probes reached Binance order validation.

**OBSERVED:** On the second sub-account, authorized through Codex CLI, the same endpoint returned `enableSpotAndMarginTrading: true`, `enableFutures: true`, `enableMargin: false`, and `enableReading: true` while the selected grant again exposed 71 tools and eleven writes. The self-report therefore differed across the two measured sub-accounts.

This is an observability gap, not a vulnerability. The endpoint an operator would query to audit the session did not describe authority consistently across measured sub-accounts and did not align with the first session's surface and invocation result. The cause remains **ASSUMED**; the finding does not depend on explaining it.

### The consent label and effective surface diverged

**OBSERVED:** The consent toggle labelled **Spot & Margin trading** produced `mcp:spot:trade`, and no margin write tool appeared under that grant.

**NOT MEASURED:** Whether the measured account was margin-eligible. The divergence may therefore reflect the label, account eligibility, sub-account configuration, or a combination. Enforcement was not shown to be weak.

### Confirmation before validation was client-dependent

**OBSERVED:** A deliberately non-executing Spot `LIMIT BUY` for `0.00001` BTC at `0.01` USDT reached Binance filter validation with `-1013 Filter failure: PERCENT_PRICE_BY_SIDE` by direct gateway call and through Claude Code at its default permission mode. In Claude Code manual permission mode a prompt was shown and the operator declined. Codex CLI default mode also displayed a prompt before its compact MCP dispatcher stopped on a tool-name error, before Binance validation.

| Path | Confirmation | Evidence |
|---|---|---|
| Direct gateway call | none | `evidence/raw/0007-full-proof-probes.jsonl` |
| Claude Code, default permission mode | none | `evidence/raw/0010-client-matrix.jsonl` |
| Claude Code, manual permission mode | prompt shown; operator declined | `evidence/raw/0010-client-matrix.jsonl` |
| Codex CLI, default permission mode | prompt shown; dispatcher stopped before Binance | `evidence/raw/0012-codex-cli-second-account.jsonl#141` |

**DOCUMENTED:** Binance describes every trade or transfer as confirmed by the user first.

**NOT MEASURED:** Whether a server-side confirmation exists after successful validation and before execution. No valid order was allowed to reach execution, so this build makes no claim about that step.

### Enforcement behaved as documented

**OBSERVED:** The selected grant exposed eleven write tools on both measured sub-accounts. Each product path reached a parameter-rejection response in both capability runs while every individual probe's complete before/after state proof remained identical.

| Capability | Advertised writes | Original result | Second-account result | Result |
|---|---:|---|---|---|
| Spot | 3 | `spot.newOrder`, `-1013` | `spot.newOrder`, `-1100` | **VERIFIED** |
| USDⓈ-M futures | 4 | `futures_usds.newOrder`, `-4013` | `futures_usds.newOrder`, `-4013` | **VERIFIED** |
| COIN-M futures | 4 | `futures_coin.newOrder`, `-1111` | `futures_coin.newOrder`, `-4013` | **VERIFIED** |
| Margin | 0 | — | — | **DENIED** at discovery |
| Convert | 0 | — | — | **DENIED** at discovery |
| Transfer | 0 | — | — | **DENIED** at discovery |

**OBSERVED:** The account-only grant advertised 60 read tools. The selected grant advertised 71 tools on both accounts, adding eleven write tools for Spot, USDⓈ-M Futures, and COIN-M Futures. The positive control `spot.getAccount` passed in the same session, client, address, and minute as each probe. The second-run Spot `-1100` response was a parameter-format rejection from the model's numeric proposal; the deterministic classifier records it as a known parameter rejection, and later proposals are normalized to fixed decimal strings.

### Effective authority and least privilege

**OBSERVED:** The same authenticated sub-account was measured under:

| Grant | Surface |
|---|---:|
| `mcp:account:read` | 60 tools |
| `mcp:account:read mcp:futures:trade mcp:spot:trade` | 71 tools |

**OBSERVED:** The checksummed strategy manifest needs Spot for `BTCUSDT` and `ETHUSDT`. The measured grant also verified both futures product families, producing measured excess of `coin_m_futures` and `usd_m_futures` and eight measured excess write tools. Narrowing requires disconnecting and re-authorizing.

**OBSERVED:** The venue lists 1,362 spot instruments trading; the strategy declares 2. The venue inventory is a potential surface only and is never added to measured authority.

### Financial reach

**OBSERVED:** Both capability runs measured empty Agentic sub-accounts.

```text
Capital visible                                  0
Capital reachable by verified trading paths     0
Autonomous capital at risk                       0
Spot holdings                                    0
Immediate exit cost                              0
Open futures positions                           0
```

**OBSERVED:** The current autonomous-capital figure is zero because both measured accounts were empty. Codex CLI default mode displayed a client prompt, while Claude Code default mode did not; the empty-account result is not a funded-capital measurement.

### Zero-state proof

**OBSERVED:** Every current probe captures fourteen state components before and after. Each snapshot is canonicalized, SHA-256 hashed, and linked into its append-only evidence chain.

```text
records replayed        250
state digests seen       14
distinct states           3
identical throughout   False
probe pairs identical   True
chain unbroken         True
```

**OBSERVED:** Every completed before/after probe pair is identical and every evidence file replays with an unbroken record chain. The aggregate contains separate account sessions, and optional wallet metadata changed between two captures, so aggregate snapshot identity is not asserted as a single state. A probe with incomplete or changed before/after proof is discarded.

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
- A narrow Claude boundary: proposal planning and unmatched-response interpretation only; the model never receives a Binance client.

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

Model-assisted planning uses the `keyring plan-probe` subcommand with a discovered tool schema and live filters. Use `--claude-code` to call the logged-in Claude Code CLI, or `--model-assisted` with `ANTHROPIC_API_KEY` and an explicit `KEYRING_MODEL` for the API adapter. Both adapters are text-only and pass no Binance session or tools to Claude. The `keyring interpret-response` subcommand accepts the same model choices and only sends unmatched responses to Claude for a proposal.

Raw responses are in [`evidence/raw/`](evidence/raw/), with credential-shaped values redacted. The measured method is in [`docs/m0.md`](docs/m0.md); the findings are in [`docs/findings.md`](docs/findings.md).

## Distribution roadmap

**DOCUMENTED:** KEYRING is not published as an MCP server. A hosted MCP server cannot introspect another MCP server's session: they are separate security contexts, and a hosted KEYRING would have no access to the Binance session it audits. The natural distribution model is a local sidecar running on the operator's machine, exposing a tool such as `what_am_i_allowed_to_do()` to a client that already holds the session, with no third party seeing the token. That is roadmap, not built. Today KEYRING is run by an operator against their own account.

## Scope

**OBSERVED:** The current evidence measures two authenticated Binance Agentic sub-accounts: the original through Claude Code and the second through Codex CLI, with a direct gateway baseline. Both use `mcp:account:read mcp:futures:trade mcp:spot:trade` for the selected capability run.

**DOCUMENTED:** Binance security guidance says not to paste the MCP endpoint into an AI chat or open it directly in a browser. The build follows that guidance.

**OBSERVED:** Rate limiting is enforced in code: a hard probe budget, per-minute pacing, `429` backoff, immediate `418` stop, `403` halt, and no aggressive retry after a server failure.
