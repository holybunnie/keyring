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
| **Claude Code**, a DOCUMENTED supported client, at its default settings | **none** | `evidence/raw/0010` |

**OBSERVED:** `spot.newOrder` reached Binance's order-filter validation and returned `-1013 Filter failure: PERCENT_PRICE_BY_SIDE`. The operator was never asked to approve anything, in either path.

**OBSERVED:** No `allowedTools` entries and no `defaultMode` override were configured, so the client ran its default permission mode. This is out-of-the-box behaviour, not a setting that had been weakened.

**DOCUMENTED:** The Binance MCP page states *"Every trade / transfer — Confirmed by you first"*, and that the confirm-before-execute pattern applies to every non-read action.

### What this is, stated precisely

**This is not a vulnerability and is not reported as one.** The token is the credential; a holder of a valid OAuth token can call the API, which is how OAuth works. Binance's gateway is not failing to enforce a control it claims to enforce at the gateway.

The finding is narrower, and does not depend on any weakness:

> The confirmation is a property of the client, not of Binance. Authority does not change when you switch clients. Protection does — and in the one supported client measured here, at its defaults, there was none.

**ASSUMED:** That the confirmation is therefore a client-side and client-configuration-side property. Two observations support it. Six supported clients remain unmeasured, and the grid that would establish it is specified in [`client-matrix.md`](client-matrix.md).

**ASSUMED:** That a different Claude Code permission mode, or a larger or fillable order, would also produce no prompt. Untested. The client's own description of its default mode says it assesses each call and runs the ones it judges lower-risk, so a different order may well be treated differently. Row 2 establishes default behaviour for this order only.

**OBSERVED:** What a user cannot do is see any of this. No screen in the authorization flow states which client enforces confirmation, or that the choice of client and its settings determines whether the promise holds.

## Zero state change, proved rather than asserted

**OBSERVED:** Every probe captures a complete financial-state snapshot before and after: spot account and open orders, wallet balances across all wallets, all-coin information, USDⓈ-M positions / balance / open orders, COIN-M positions / balance / open orders, cross-margin account detail and open orders, convert open orders, and spot trade-history head. Fourteen component reads per snapshot, defined in the checksummed `config/state_snapshot.yaml`.

**OBSERVED:** Each snapshot is canonicalised and hashed with SHA-256, and the digests are chained across the session.

```
records replayed        105
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

## Limits

**INCONCLUSIVE:** M0.5, whether permissions can be narrowed in place, is not resolved. It requires an action in the Binance web UI that this build cannot perform.

**INCONCLUSIVE:** The client matrix is incomplete. See [`client-matrix.md`](client-matrix.md).

**INCONCLUSIVE:** No `ADVERTISED_ONLY` case, no `-2015` response, and no autonomous-execution observation beyond the single ungated invocation described above.

**OBSERVED:** All probing ran from a GB egress address. The prober was never hosted on a US IP.

## The contradictions table, measured

Part 0.4 records four questions on which first-party Binance sources describe the same system differently. Three now have a measured answer.

| Question | Source A | Source B | Measured |
|---|---|---|---|
| Can permissions be narrowed in place? | MCP docs: disconnect and reconnect to update | Launch blog: permissions reviewable **or changeable** under Account Management | **`RECONNECT_REQUIRED`** — OBSERVED. The View permissions screen lists permissions and offers no control to change them. Source A is supported. Corroborated independently: this build's grant changed only across a full logout and re-authorization, never within a session. |
| Is confirmation always required? | MCP docs: applies to **every** non-read action | Support FAQ: flows are *designed to* request confirmation before consequential actions | **The gate is not at the gateway** — OBSERVED. Three probes reached parameter validation with no confirmation step. ASSUMED, not established: that the gate therefore sits in the client. See [`client-matrix.md`](client-matrix.md) for the experiment that would establish it. |
| Does autonomous execution exist? | Academy: users may require per-order approval **or allow autonomous trading** | MCP docs: no autonomous mode mentioned | **An invocation reached Binance without a human click** — OBSERVED. Whether any client exposes this as a configurable "autonomous mode" is **INCONCLUSIVE**; no such setting was observed and none was looked for programmatically. |
| What does Emergency Stop do? | MCP docs: cancels all spot, margin and futures **positions and orders** | Support FAQ: behaviour can vary by product | **Not measured, by design.** Triggering it is out of scope (Part 0.4). The disagreement is published, not resolved. |

**OBSERVED:** The first row was resolved by one observation, and it is the one with the sharpest consequence for users: an over-broad grant cannot be trimmed, only torn down and rebuilt.
