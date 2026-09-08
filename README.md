# KEYRING

> Binance shows you what you authorized. KEYRING measures what that authorization can actually do.

> No exploits. Explicitly approved measurement. No guessing. Just measured authority.

> Two Binance accounts. Two AI clients. Four places that answer “what can this agent do?” — and they disagreed. Every number below regenerates from saved responses.

## What can this agent actually do?

**OBSERVED · harness:** The permission screen, Binance's own permission check,
the tools handed to the agent, and controlled tests answered different parts of
the same question. The comparison below is rebuilt from the evidence log.

| Account | Permission screen | Binance's own permission check | Tools handed to the agent | Controlled tests |
|---|---|---|---|---|
| Account A | Spot & Margin trading · Futures | Spot ✕ · Futures ✕ | 71 tools · 11 trading writes | Spot ✓ · USDⓈ-M ✓ · COIN-M ✓ |
| Account B | Spot & Margin trading · Futures | Spot ✓ · Futures ✓ | 71 tools · 11 trading writes | Spot ✓ · USDⓈ-M ✓ · COIN-M ✓ |

**OBSERVED · harness:** Account A reported Spot and Futures trading disabled.
Account B reported them enabled. Both trade-grant surfaces exposed the same 71
tools and 11 writes, and KEYRING independently confirmed the same three trading
families on both.

**Same permission set. Same measured trading surface. Different self-report.**

## Safety boundary

**OBSERVED · harness:** The authority tests were requests built to fail at
exchange checks before execution. Each had a connection check and a complete
before/after account-state snapshot. A separate buy/sell measurement was
explicitly approved and is reported separately.

## The agent

**OBSERVED · harness:** KEYRING loads the tool schema Binance discovers at runtime
together with the target symbol's live exchange filters, and the agent uses them
to propose a trading-shaped test: the tool, the arguments, the specific filter it
expects to violate, and a written justification.

**OBSERVED · harness:** The model cannot execute directly. Every proposal must
pass a deterministic non-execution gate — `planner.validate_proposal` requires
the notional to fall below the live `MIN_NOTIONAL` and a named live filter to be
violated — before the harness may send it. Only then does it run, safety-wrapped,
with a connection check and a full before/after state snapshot. Responses no
deterministic matcher recognises go back to the model for interpretation, and
the deterministic classifier owns the published result.

**OBSERVED · harness:** The gate is the feature. Every probe record carries
`planned_by` and the model's reasoning. Where the model and classifier
disagreed, both are preserved verbatim — including active record
[`0012#78`](evidence/raw/0012-codex-cli-second-account.jsonl#L78), where the
model proposed `VERIFIED` and the deterministic result was `INCONCLUSIVE`.
Every recorded authority test was rejected before execution and left financial
state unchanged.

The historical evidence remains unchanged. Older probe records are shown as
planning fields not recorded, rather than falsely labelled as model output.

## Results

### The permission self-report diverged by sub-account

**OBSERVED · harness:** On the original Claude Code sub-account, Binance's own permission check reported Spot and Futures trading disabled: `enableSpotAndMarginTrading: false`, `enableFutures: false`, and `enableReading: true` under both measured grants. At the same time, the trade-grant surface advertised eleven trading write tools and three controlled tests reached Binance order validation.

**OBSERVED · harness:** On the second sub-account, authorized through Codex CLI, the same endpoint returned `enableSpotAndMarginTrading: true`, `enableFutures: true`, `enableMargin: false`, and `enableReading: true` while the selected grant again exposed 71 tools and eleven writes. The self-report therefore differed across the two measured sub-accounts.

This result was observed on two Agentic sub-accounts through two supported clients: Claude Code on the original account ([raw permission record](evidence/raw/0005-m0-run-b.jsonl)) and Codex CLI on the second ([raw permission record](evidence/raw/0012-codex-cli-second-account.jsonl)).

This is an observability gap, not a vulnerability. The endpoint an operator would query to audit the session did not describe authority consistently across the two measured sub-accounts, while both sessions exposed the same measured trading surface. The cause remains **ASSUMED**; the finding does not depend on explaining it.

### The consent label and the effective surface diverged

**OBSERVED · operator:** The consent toggle labelled **Spot & Margin trading** produced `mcp:spot:trade`, and no margin write tool appeared under that grant.

**NOT MEASURED:** Whether the measured account was margin-eligible. The divergence may therefore reflect the label, account eligibility, sub-account configuration, or a combination. Enforcement was not shown to be weak.

### Confirmation before validation was client-dependent

**OBSERVED · harness:** A deliberately non-executing Spot `LIMIT BUY` for `0.00001` BTC at `0.01` USDT reached Binance filter validation with `-1013 Filter failure: PERCENT_PRICE_BY_SIDE` by direct gateway call.

**OBSERVED · operator:** Claude Code at its default permission mode also reached validation without a prompt. In Claude Code manual permission mode a prompt was shown and the operator declined. Codex CLI default mode displayed a prompt before its compact MCP dispatcher stopped on a tool-name error, before Binance validation.

| Path | Confirmation | Evidence |
|---|---|---|
| Direct gateway call | none · harness | `evidence/raw/0007-full-proof-probes.jsonl` |
| Claude Code, default permission mode | none · operator | `evidence/raw/0010-client-matrix.jsonl` |
| Claude Code, manual permission mode | prompt shown; operator declined · operator | `evidence/raw/0010-client-matrix.jsonl` |
| Codex CLI, default permission mode | prompt shown; dispatcher stopped before Binance · operator | `evidence/raw/0012-codex-cli-second-account.jsonl#141` |

**DOCUMENTED:** Binance describes every trade or transfer as confirmed by the user first.

**NOT MEASURED:** Whether a server-side confirmation exists after successful validation and before execution. No valid order was allowed to reach execution, so this build makes no claim about that step.

### Enforcement behaved as documented

**OBSERVED · harness:** The selected grant exposed eleven trading write tools on both measured sub-accounts. Each product path reached a parameter-rejection response in both capability runs while every individual test's complete before/after state proof remained identical.

| Capability | Advertised writes | Original result | Second-account result | Result |
|---|---:|---|---|---|
| Spot | 3 | `spot.newOrder`, `-1013` | `spot.newOrder`, `-1100` | **VERIFIED** |
| USDⓈ-M futures | 4 | `futures_usds.newOrder`, `-4013` | `futures_usds.newOrder`, `-4013` | **VERIFIED** |
| COIN-M futures | 4 | `futures_coin.newOrder`, `-1111` | `futures_coin.newOrder`, `-4013` | **VERIFIED** |
| Margin | 0 | — | — | **DENIED** at discovery |
| Convert | 0 | — | — | **DENIED** at discovery |
| Transfer | 0 | — | — | **DENIED** at discovery |

**OBSERVED · harness:** The account-only grant advertised 60 read tools. The selected grant advertised 71 tools on both accounts, adding eleven trading write tools for Spot, USDⓈ-M Futures, and COIN-M Futures. The connection check `spot.getAccount` passed in the same session, client, address, and minute as each test. The second-run Spot `-1100` response was a parameter-format rejection from the model's numeric proposal; the deterministic classifier records it as a known parameter rejection, and later proposals are normalized to fixed decimal strings.

### What the agent needs versus what it has

**OBSERVED · harness:** The same authenticated sub-account was measured under:

| Grant | Surface |
|---|---:|
| `mcp:account:read` | 60 tools |
| `mcp:account:read mcp:futures:trade mcp:spot:trade` | 71 tools |

**OBSERVED · harness:** The checksummed strategy manifest needs Spot for `BTCUSDT` and `ETHUSDT`. The measured grant also verified both futures product families, producing measured excess of `coin_m_futures` and `usd_m_futures` and eight measured excess write tools. Narrowing requires disconnecting and re-authorizing.

**OBSERVED · harness:** The venue lists 1,362 spot instruments trading; the strategy declares 2. The venue inventory is a potential surface only and is never added to measured authority.

### Financial reach

**OBSERVED · harness:** The second Agentic sub-account was funded separately after its
capability measurement. The initial complete snapshot found `5.60000000 USDT`
in its Spot account. The approved measurement bought `0.00007 BTC`, paid
`0.00000007 BTC` commission, and sold `0.00006 BTC` because the LOT_SIZE step
was `0.00001`. No Binance-retained dust is claimed; the remaining quantity
reflected the sell sizing.

**OBSERVED · harness:** Capital and confirmation are reported by provenance, never as a
single cross-client summary:

| Account / client / mode | Reachable capital | Before dispatch | Autonomous capital at risk |
|---|---:|---|---:|
| Account A / Claude Code / default | `0 USDT` | no confirmation observed · operator | `0 USDT` — account empty |
| Account A / Claude Code / manual | `0 USDT` | prompt shown; operator declined · operator | `0 USDT` — account empty |
| Account B / Codex CLI / default | `5.59 USDT` | prompt shown before dispatch · operator | `0 USDT` — client gate observed |
| Account A / Direct gateway | — | no confirmation observed · harness | — |

**OBSERVED · harness:** The dashboard displays the funded balance as `5.59 USDT`; the linked trace and evidence retain the exact `5.58854065 USDT` reading.

```text
Capital visible                           5.58854065 USDT
Capital reachable by verified trading paths 5.58854065 USDT
Autonomous capital at risk                       0
Spot holdings                                    2
Open futures positions                           0
```

**OBSERVED · operator:** For Account B through Codex CLI's default mode, autonomous
capital at risk is zero because the client displayed a confirmation prompt
before dispatch. The approved measurement used one bounded Spot buy and one
Spot sell solely to create and close a small BTC holding; no Futures, transfer,
or withdrawal was sent.

**OBSERVED · harness:** The live BTCUSDT bid book was walked for the post-buy holding.
The measured immediate exit cost was `0.0054753406785 USDT`, including the
estimated taker fee.

### Revocation

**OBSERVED · operator:** In one Codex CLI trial, five recorded `spot.getAccount` reads
were permitted. After the operator disconnected the agent, the next recorded
read returned a transport-level `Auth required` failure. Revocation was therefore
observed at the Agentic session boundary, with `n=1`; no reconnect followed.

The timestamped interval from the last permitted response to the first denied
response was `20.680 seconds`. This is an observation window, not a claimed
UI-click-to-denial latency, because the web UI click was not timestamped inside
the recording process. Evidence: [`0017-codex-cli-second-account-revocation-20260908.jsonl`](evidence/raw/0017-codex-cli-second-account-revocation-20260908.jsonl).

### Every authority test left financial state unchanged

**OBSERVED · harness:** Every current authority test captures fourteen state components
before and after. Each snapshot is canonicalized, SHA-256 hashed, and linked
into its append-only evidence chain.

```text
records replayed        329
state digests seen       18
distinct states           7
identical throughout   False
probe pairs identical   True
chain unbroken         True
```

**OBSERVED · harness:** Every completed before/after probe pair is identical and every evidence file replays with an unbroken record chain. The aggregate contains separate account sessions, and optional wallet metadata changed between two captures, so aggregate snapshot identity is not asserted as a single state. A probe with incomplete or changed before/after proof is discarded.

## What problem this solves

An Agentic consent grant, a gateway tool surface, a client confirmation policy, and a credential self-report are different evidence surfaces. KEYRING joins them into one replayable answer to: **what can this connected session actually reach, what did it attempt, and did the audit change financial state?**

The result is an evidence-derived authority map, proof trace, least-privilege comparison, layered financial-reach view, and read-only dashboard. It detects disagreements between first-party surfaces without calling those disagreements exploits.

## What we built

- Runtime MCP discovery with raw responses and granted-scope evidence.
- A connection check and one budgeted, deliberately non-executing test per measured capability.
- Complete before/after financial snapshots with canonical digests and append-only hash chains.
- Deterministic authority classification, least-privilege diff, and layered financial reach.
- Permission traces in which every classification line resolves to evidence.
- A read-only dashboard rebuilt from the current classifier path.
- An agent boundary: the model proposes safe tests and interprets unmatched responses; deterministic code checks proposals and owns every result.

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

The retained evidence includes the recorded end-to-end agent run. It is the
replayable artifact for the agent flow: runtime schema and live filters → model
proposal → deterministic gate → safety-wrapped request → deterministic result.
The commands above regenerate the analysis without reconnecting to Binance.

There is no `agent-probe` command in this submission: invoking it would perform
a new live measurement. The retained run is the evidence used for the agent
flow, and the commands above replay its results without a live session.

For an externally reachable demo, bind the read-only server explicitly:

```bash
python -m keyring dashboard --host 0.0.0.0 --port 8080
```

Model-assisted planning uses the `keyring plan-probe` subcommand with a discovered tool schema and live filters. Use `--claude-code` to call the logged-in Claude Code CLI, or `--model-assisted` with `ANTHROPIC_API_KEY` and an explicit `KEYRING_MODEL` for the API adapter. Both adapters are text-only and pass no Binance session or tools to Claude. The `keyring interpret-response` subcommand accepts the same model choices and only sends unmatched responses to Claude for a proposal.

Raw responses are in [`evidence/raw/`](evidence/raw/), with credential-shaped values redacted. The measured method is in [`docs/m0.md`](docs/m0.md); the findings are in [`docs/findings.md`](docs/findings.md).

## Distribution roadmap

**DOCUMENTED:** KEYRING is not published as an MCP server. A hosted MCP server cannot introspect another MCP server's session: they are separate security contexts, and a hosted KEYRING would have no access to the Binance session it audits. The natural distribution model is a local sidecar running on the operator's machine, exposing a tool such as `what_am_i_allowed_to_do()` to a client that already holds the session, with no third party seeing the token. That is roadmap, not built. Today KEYRING is run by an operator against their own account.

## Scope

**OBSERVED · harness:** The current evidence measures two authenticated Binance Agentic sub-accounts: the original through Claude Code and the second through Codex CLI, with a direct gateway baseline. Both use `mcp:account:read mcp:futures:trade mcp:spot:trade` for the selected capability run.

**DOCUMENTED:** Binance security guidance says not to paste the MCP endpoint into an AI chat or open it directly in a browser. The build follows that guidance.

**OBSERVED · harness:** Rate limiting is enforced in code: a hard probe budget, per-minute pacing, `429` backoff, immediate `418` stop, `403` halt, and no aggressive retry after a server failure.

## Limits

**NOT MEASURED:** Whether Binance inserts a server-side confirmation after a
request passes validation and before execution. No valid order was allowed to
reach that step.

**NOT MEASURED:** Whether the measured account was margin-eligible. The
consent-label divergence is not attributed to one cause.

**INCONCLUSIVE:** A futures gross-notional ceiling is not asserted because
leverage brackets, margin mode, and account limits were not resolved.

**ASSUMED:** The cause of the different permission self-reports is not
established by this run.

**Egress metadata:** Probe records carry `egress_country: GB` as run metadata
describing the measurement infrastructure. It is a static field written by
the harness, not measured geolocation, and it does not describe the
participant's location. Participant eligibility is established separately
through the hackathon submission process.
