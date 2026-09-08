# KEYRING — findings

Every claim here is **OBSERVED**, **DOCUMENTED** or **ASSUMED** (Law 1). Every OBSERVED claim regenerates from the append-only evidence log by running:

```
python -c "import sys;sys.path.insert(0,'src');from keyring.authority import derive,render;print(render(derive()))"
```

## Headline

**OBSERVED:** The confirmation step users are promised did not appear anywhere in the tested path.

Two independent observations:

| Path | Confirmation | Evidence |
|---|---|---|
| Direct call to the gateway with a valid session token | **none** | `evidence/raw/0007` |
| **Claude Code**, a DOCUMENTED supported client, **default settings** | **none** | `evidence/raw/0010` |
| **Claude Code**, same client and credential, **`--permission-mode manual`** | **prompts** | `evidence/raw/0010` |

**OBSERVED:** The third row differs from the second in exactly one variable: the client's permission mode. Same client, same credential, same order.

**OBSERVED:** In the tested Claude Code path, the confirmation Binance documents was not added by the gateway. Claude Code's default mode was permissive; its manual mode prompted.

**OBSERVED:** `spot.newOrder` reached Binance's order-filter validation and returned `-1013 Filter failure: PERCENT_PRICE_BY_SIDE`. The operator was never asked to approve anything in the direct gateway or Claude Code default paths.

**OBSERVED:** No `allowedTools` entries and no `defaultMode` override were configured, so the client ran its default permission mode. This is out-of-the-box behaviour, not a setting that had been weakened.

**DOCUMENTED:** The Binance MCP page states *"Every trade / transfer — Confirmed by you first"*, and that the confirm-before-execute pattern applies to every non-read action.

### What this is, stated precisely

**This is not a vulnerability and is not reported as one.** The token is the credential; a holder of a valid OAuth token can call the API, which is how OAuth works. Binance's gateway is not failing to enforce a control it claims to enforce at the gateway.

The finding is narrower, and does not depend on any weakness:

> In the measured paths, the gateway did not add confirmation. Claude Code at its default settings added none; Claude Code's manual mode did. This audit does not generalize to other clients or executable-sized orders.

**INCONCLUSIVE:** Other clients and executable-sized orders were not measured. They are outside this audit's scope; no claim is made about them.

**OBSERVED:** The permission-mode confound is closed. Under `--permission-mode manual` the same client asked before invoking; under its default it did not. The absence of a prompt was a function of the client's default configuration, not of the order being small.

**ASSUMED:** That a larger or fillable order would also produce no prompt under the default mode. Untested, and deliberately so: testing it would require an order capable of executing, which Part XIV forbids and which would forfeit the zero-state-change property.

**OBSERVED:** What a user cannot do is see any of this. No screen in the authorization flow states which client enforces confirmation, or that the choice of client and its settings determines whether the promise holds.

## Zero state change, proved rather than asserted

**OBSERVED:** Every probe captures a complete financial-state snapshot before and after: spot account and open orders, wallet balances across all wallets, all-coin information, USDⓈ-M positions / balance / open orders, COIN-M positions / balance / open orders, cross-margin account detail and open orders, convert open orders, and spot trade-history head. Fourteen component reads per snapshot, defined in the checksummed `config/state_snapshot.yaml`.

**OBSERVED:** Each snapshot is canonicalised and hashed with SHA-256, and the digests are chained across the session.

```
records replayed        109
state digests seen        6
distinct states           1
identical throughout   True
chain unbroken         True
```

**OBSERVED:** Every snapshot taken across the entire audit hashed to the same value. The claim is not "this probe changed nothing" but "nothing changed across the whole audit, and here is the unbroken chain".

**OBSERVED:** A probe whose snapshots are incomplete or unequal is discarded, not reported. This is enforced in `prober.py`, not by convention. One early probe was discarded on exactly this basis and is retained in `evidence/superseded/` with the reason recorded. Its hash was not recomputed to make it pass.

## Effective authority, measured

**OBSERVED:** Under a grant of `mcp:account:read mcp:futures:trade mcp:spot:trade`:

| Capability | Advertised write tools | Probe | Code | State | Classification |
|---|---|---|---|---|---|
| Spot | 3 | `spot.newOrder` | `-1013` | IDENTICAL | **VERIFIED** |
| USDⓈ-M futures | 4 | `futures_usds.newOrder` | `-4013` | IDENTICAL | **VERIFIED** |
| COIN-M futures | 4 | `futures_coin.newOrder` | `-1111` | IDENTICAL | **VERIFIED** |
| Margin | 0 | not probed | — | — | **DENIED** at discovery |
| Convert | 0 | not probed | — | — | **DENIED** at discovery |
| Transfer | 0 | not probed | — | — | **DENIED** at discovery |

**OBSERVED:** The positive control (`spot.getAccount`) passed in the same session, client, address and minute as every probe (Law 4).

## Enforcement behaved as documented across the full tested surface

**OBSERVED:** Across **2 scope combinations**, **6 capabilities** and **3 invocation probes**, the advertised tool surface matched the granted scope in every case. No capability was advertised that the grant could not exercise, and no capability was exercisable that was not advertised.

**OBSERVED:** `tools/list` returned 60 tools under `mcp:account:read` and 71 under `mcp:account:read mcp:futures:trade mcp:spot:trade`. The eleven additional tools are exactly the write operations for the two products whose trade scope was granted. No tool disappeared.

**OBSERVED:** Under the Account-only grant, no capability to create, amend or cancel an order was advertised at all.

**OBSERVED: no `ADVERTISED_ONLY` case was produced.** Discovery filtering and granted scope agreed everywhere they were tested. This is stated as a finding, not as an absence of one: Binance Agentic permission enforcement behaved as documented across the full tested surface.

**INCONCLUSIVE:** No `-2015` response was produced by any probe, so the DOCUMENTED ambiguity of that code (credential vs IP vs permission) remains untested here.

## Granted versus effective — the one gap that is real

**OBSERVED:** `wallet.getApiKeyPermission` returned an identical payload under both grants, reporting `enableSpotAndMarginTrading: false`, `enableFutures: false`, `enableMargin: false`, `enableInternalTransfer: false`, `enableWithdrawals: false`, `enableReading: true`.

**OBSERVED:** In the second grant that report coexists with eleven advertised trading tools, a scope containing `mcp:spot:trade` and `mcp:futures:trade`, and three probes that reached order validation.

**ASSUMED:** The likely explanation is that this endpoint reports the permission bits of a legacy API-key object and is not wired to OAuth scope grants. This is not verified and is not published as a defect.

**OBSERVED:** An operator who audits this agent by asking Binance what the credential may do receives an answer that does not reflect the scope actually granted.

**OBSERVED:** The consent toggle labelled "Spot & Margin trading" produced the scope `mcp:spot:trade`. No margin write tool appeared under it.

**INCONCLUSIVE:** Whether margin write capability requires the separate "Enable Margin Loan, Repay & Transfer" toggle, which was left off, is unresolved.

## Run C — no eligibility denial found

**OBSERVED:** Part IV M0.4 Run C sought a product the account is not eligible for, under a grant including Trade. Both futures products were probed. USDⓈ-M returned `-4013 Price less than min price`; COIN-M returned `-1111 Precision is over the maximum defined for this asset`. Both are parameter rejections, so both validation paths are reachable.

**OBSERVED:** No eligibility-level denial was produced. This account is eligible for every product its grant covers, so the granted-versus-effective gap does not appear at the eligibility layer in this configuration.

**ASSUMED:** A different account — one without futures enabled — would produce the denial Run C was designed to find. Untested here.

## Least-privilege diff (F3)

**OBSERVED:** The strategy's needs are read from its checksummed manifest, `config/strategy.yaml`. They are never inferred from a model.

```
LEAST-PRIVILEGE DIFF — example-spot-strategy
  derived from 109 evidence records
  granted scope   mcp:account:read mcp:futures:trade mcp:spot:trade

NEEDED       (declared in the manifest, never inferred)
  capabilities   spot
  instruments    2  (BTCUSDT, ETHUSDT)

EFFECTIVE    (measured, VERIFIED by probe with a passing control)
  capabilities   coin_m_futures, spot, usd_m_futures

EXCESS — MEASURED
  capabilities   coin_m_futures, usd_m_futures
  write tools    8
    futures_coin.cancelOrder
    futures_coin.changeInitialLeverage
    futures_coin.changeMarginType
    futures_coin.newOrder
    futures_usds.cancelOrder
    futures_usds.changeInitialLeverage
    futures_usds.changeMarginType
    futures_usds.newOrder

EXCESS — POTENTIAL  (POTENTIAL_SURFACE_ONLY)
  venue lists    1362 spot instruments trading
  strategy needs 2
  excess         1360  — OBSERVED (venue listing), NOT measured reach

REMEDIATION COST
  RECONNECT_REQUIRED  — OBSERVED
  An over-broad grant cannot be narrowed. It must be disconnected
  and re-authorized from scratch.
```

**OBSERVED — measured excess.** 2 entire product families the manifest explicitly declines are VERIFIED on this grant, exposing 8 write tools the strategy has no use for. This is measured: each was probed, each reached order validation, each had a passing positive control and an identical state digest.

**OBSERVED (venue listing), NOT measured reach — potential excess.** The venue lists 1,362 spot instruments trading. The manifest needs 2. **This is not presented as effective authority.** Only the probed symbol has measured evidence behind it, and Part IX forbids printing a listed instrument count as measured reach. The two excess figures are reported separately and are never added together.

**OBSERVED — the remediation cost is measured, not asserted.** Narrowing this grant is not an edit. `RECONNECT_REQUIRED` means the agent must be disconnected and re-authorized from scratch, and the value is read from the evidence log rather than written by hand.

**Reproduce it:**

```bash
python -m keyring least-privilege
```

## Financial reach, layered (F2)

**OBSERVED:** One number would be dishonest, because these are different quantities. Each layer below carries its own label, its own reason, and the snapshot components it was derived from. A layer whose inputs are missing is INCONCLUSIVE, never zero — absence of evidence is not a measurement of zero.

```
FINANCIAL REACH, LAYERED

  Capital visible                                  0   OBSERVED
      sum of every wallet balance in the latest complete snapshot; denominated as the API returned it, with no quoteAsset requested

  Capital reachable by trading                     0   OBSERVED
      capital held in wallets whose trading capability was probed and classified VERIFIED (COIN-M Futures, Spot, USDⓈ-M Futures)

  Autonomous capital at risk                       0   OBSERVED
      no confirmation step was observed in the tested client default, so all reachable capital could move without a human approving it. This figure is currently zero because the account is empty, NOT because a gate exists.

  Spot holdings (non-zero assets)                  0   OBSERVED
      spot balances with a non-zero free or locked amount

  Immediate exit cost                              0   OBSERVED
      there are no holdings to exit, so the cost is zero by absence rather than by an order-book walk

  Futures gross notional ceiling        INCONCLUSIVE   INCONCLUSIVE
      leverage brackets, margin mode and account limits are not resolved; a gross notional ceiling is not derivable from this evidence and is not asserted

  Open futures positions            {'usds_positions': 0, 'coinm_positions': 0}   OBSERVED
      positions with a non-zero amount across both futures products

  INSTRUMENTS
      capabilities verified        coin_m_futures, spot, usd_m_futures
      spot symbols probed          1
      spot symbols listed trading  1362
      Reach is reported as probed versus listed. A listed instrument count is the venue's surface, not measured reach, and the two are never merged.
```

**OBSERVED — the autonomous line is the one that matters, and its reason is not the one the design anticipated.** The layered view was specified with an example reading `Autonomous capital at risk $0 — confirmation required`. That reason is false for this account. No confirmation step was observed in the tested client default, so **all reachable capital could move without a human approving it**. The figure is zero because the account is empty, not because a gate exists. A test asserts that a zero here can never be attributed to a gate that was not observed.

**INCONCLUSIVE — the futures gross notional ceiling is refused, not estimated.** Leverage brackets, margin mode and existing positions all bear on it, and none is resolved by this evidence. Publishing an estimate would be a guess wearing a number's clothing.

**OBSERVED — reach is reported as probed versus listed.** The venue's listed instrument count is not measured reach, and the two are never merged into a single figure.

**Reproduce it:**

```bash
python -m keyring financial-reach
```

## Limits

**OBSERVED:** M0.5 resolved as `RECONNECT_REQUIRED`. The View permissions screen had no edit control; narrowing requires disconnecting and re-authorizing.

**INCONCLUSIVE:** Other clients were not measured. Cross-client behaviour is outside this audit's scope; no claim is made about it. See [`client-matrix.md`](client-matrix.md).

**INCONCLUSIVE:** No `ADVERTISED_ONLY` case, no `-2015` response, and no autonomous-execution observation beyond the single ungated invocation described above.

**OBSERVED:** All probing ran from a GB egress address. The prober was never hosted on a US IP.

## The contradictions table, measured

Part 0.4 records four questions on which first-party Binance sources describe the same system differently. Three now have a measured answer.

| Question | Source A | Source B | Measured |
|---|---|---|---|
| Can permissions be narrowed in place? | MCP docs: disconnect and reconnect to update | Launch blog: permissions reviewable **or changeable** under Account Management | **`RECONNECT_REQUIRED`** — OBSERVED. The View permissions screen lists permissions and offers no control to change them. Source A is supported. Corroborated independently: this build's grant changed only across a full logout and re-authorization, never within a session. |
| Is confirmation always required? | MCP docs: applies to **every** non-read action | Support FAQ: flows are *designed to* request confirmation before consequential actions | **The gateway did not gate the measured paths** — OBSERVED. Direct invocation and Claude Code's default mode reached parameter validation without a prompt; Claude Code's manual mode prompted. Other clients are outside this audit's scope. |
| Does autonomous execution exist? | Academy: users may require per-order approval **or allow autonomous trading** | MCP docs: no autonomous mode mentioned | **An invocation reached Binance without a human click** — OBSERVED. Whether any client exposes this as a configurable "autonomous mode" is **INCONCLUSIVE**; no such setting was observed and none was looked for programmatically. |
| What does Emergency Stop do? | MCP docs: cancels all spot, margin and futures **positions and orders** | Support FAQ: behaviour can vary by product | **Not measured, by design.** Triggering it is out of scope (Part 0.4). The disagreement is published, not resolved. |

**OBSERVED:** The first row was resolved by one observation, and it is the one with the sharpest consequence for users: an over-broad grant cannot be trimmed, only torn down and rebuilt.
