KEYRING performs zero-state-change auditing. It cannot trade, transfer or revoke. It audits one Binance account using that account's own grants, and every capability probe is constructed to terminate before execution, with balances, positions and open orders verified unchanged before and after. Probing is rate-limited by design and runs at one probe per capability. KEYRING follows Binance's own guidance: **the MCP endpoint is never pasted into an AI chat and never opened in a browser.**

# KEYRING

> Binance shows you what you authorized. KEYRING measures what that authorization can actually do.

> No exploits. No transactions. No guessing. Just measured authority.

Every claim below is labelled **OBSERVED** (this build ran it and recorded the result), **DOCUMENTED** (a first-party Binance page says it), or **ASSUMED** (nobody has verified it). An unlabelled claim is a defect.

---

## The contradictions, measured

**DOCUMENTED:** First-party Binance sources describe the same controls differently in at least four places. Three now have a measured answer.

| Question | Source A | Source B | Measured |
|---|---|---|---|
| Can permissions be narrowed in place? | [MCP docs](https://developers.binance.com/en/docs/agent-native/mcp-server/agentic): disconnect and reconnect to update | [Launch blog](https://www.binance.com/en/blog/ecosystem/5991233187660196794): permissions reviewable **or changeable** under Account Management | **`RECONNECT_REQUIRED`** — OBSERVED. The View permissions screen lists permissions and offers no control to change them. Source A is supported. |
| Is confirmation always required? | [MCP docs](https://developers.binance.com/en/docs/agent-native/mcp-server/agentic): applies to **every** non-read action | [Support FAQ](https://www.binance.com/en/support/faq/detail/7a6e676e36fb455d96478932cb12d9f3): flows are *designed to* request confirmation | **No confirmation appeared in the tested path** — OBSERVED, both direct and through a supported client at its defaults. |
| Does autonomous execution exist? | [Academy](https://www.binance.com/en/academy/articles/how-binance-agent-os-is-changing-crypto-trading): per-order approval **or** autonomous trading | [MCP docs](https://developers.binance.com/en/docs/agent-native/mcp-server/agentic): no autonomous mode mentioned | **An invocation reached Binance with no human click** — OBSERVED. Whether any client exposes a configurable autonomous mode is **INCONCLUSIVE**. |
| What does Emergency Stop do? | [MCP docs](https://developers.binance.com/en/docs/agent-native/mcp-server/agentic): cancels all spot, margin and futures positions and orders | [Support FAQ](https://www.binance.com/en/support/faq/detail/7a6e676e36fb455d96478932cb12d9f3): behaviour can vary by product | **Not measured, by design.** Triggering it is out of scope. The disagreement is published, not resolved. |

---

## Results

### The confirmation is the client's, not Binance's

**OBSERVED:** A spot order reached Binance's order-filter validation and returned `-1013 Filter failure: PERCENT_PRICE_BY_SIDE`, with no confirmation requested, by two independent paths:

| Path | Confirmation |
|---|---|
| Direct call to the gateway with a valid session token | **none** |
| **Claude Code**, a DOCUMENTED supported client, at its default settings | **none** |

**OBSERVED:** No `allowedTools` entries and no `defaultMode` override were configured. The client ran out of the box.

**DOCUMENTED:** Binance states *"Every trade / transfer — Confirmed by you first."*

**This is not a vulnerability and is not reported as one.** The token is the credential; a holder of a valid OAuth token can call the API, which is how OAuth works. The finding is narrower and needs no weakness:

> The confirmation is a property of the client, not of Binance. Authority does not change when you switch clients. Protection does — and in the one supported client measured here, at its defaults, there was none. No screen in the authorization flow tells a user this.

**ASSUMED:** That this generalises to other clients or other permission modes. Six supported clients remain unmeasured; the grid that would settle it is specified in [`docs/client-matrix.md`](docs/client-matrix.md).

### Enforcement behaved as documented across the tested surface

**OBSERVED:** Across 2 scope combinations, 6 capabilities and 3 invocation probes, the advertised tool surface matched the granted scope in **every** case.

| Grant | Tools advertised |
|---|---|
| `mcp:account:read` | **60** — every one a read |
| `mcp:account:read mcp:futures:trade mcp:spot:trade` | **71** |

**OBSERVED:** The eleven additions are exactly the write operations for the two products whose trade scope was granted — `spot.newOrder`, `spot.deleteOrder`, `spot.deleteOpenOrders`, and the USDⓈ-M and COIN-M order, cancel, leverage and margin-type tools. No tool disappeared. Under the Account-only grant, no capability to create, amend or cancel an order was advertised at all.

**OBSERVED: no `ADVERTISED_ONLY` case was produced.** This is stated as a finding, not as an absence of one. Binance Agentic discovery filtering and granted scope agreed everywhere they were tested.

### Effective authority

**OBSERVED**, under `mcp:account:read mcp:futures:trade mcp:spot:trade`:

| Capability | Advertised writes | Probe | Code | State | Classification |
|---|---|---|---|---|---|
| Spot | 3 | `spot.newOrder` | `-1013` | IDENTICAL | **VERIFIED** |
| USDⓈ-M futures | 4 | `futures_usds.newOrder` | `-4013` | IDENTICAL | **VERIFIED** |
| COIN-M futures | 4 | `futures_coin.newOrder` | `-1111` | IDENTICAL | **VERIFIED** |
| Margin | 0 | not probed | — | — | **DENIED** at discovery |
| Convert | 0 | not probed | — | — | **DENIED** at discovery |
| Transfer | 0 | not probed | — | — | **DENIED** at discovery |

**OBSERVED:** The positive control (`spot.getAccount`) passed in the same session, client, address and minute as every probe.

### Granted is not the same as reported

**OBSERVED:** `wallet.getApiKeyPermission` returned an identical payload under both grants — `enableSpotAndMarginTrading: false`, `enableFutures: false`, `enableWithdrawals: false`, `enableReading: true` — while eleven trading tools were advertised and three probes reached order validation.

**ASSUMED:** That this endpoint reports a legacy API-key object and is not wired to OAuth scope grants. Not verified, and not published as a defect.

**OBSERVED:** An operator who audits this agent by asking Binance what the credential may do receives an answer that does not reflect the scope actually granted.

**OBSERVED:** The consent toggle labelled "Spot & Margin trading" produced the scope `mcp:spot:trade`. No margin write tool appeared under it.

---

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

---

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

---

## Zero state change, proved rather than asserted

**OBSERVED:** Every probe captures fourteen state components before and after — spot account and open orders, wallet balances, all-coin information, USDⓈ-M and COIN-M positions, balances and open orders, cross-margin detail and open orders, convert open orders, and spot trade-history head. The components are defined in the checksummed [`config/state_snapshot.yaml`](config/state_snapshot.yaml).

**OBSERVED:** Each snapshot is canonicalised and hashed with SHA-256, and digests are chained across the session.

```
records replayed        109
state digests seen        6
distinct states           1
identical throughout   True
chain unbroken         True
```

**OBSERVED:** Every snapshot taken across the entire audit hashed to the same value. The claim is not *this probe changed nothing* but *nothing changed across the whole audit, and here is the unbroken chain*.

**OBSERVED:** A probe whose snapshots are incomplete or unequal is discarded, not reported, and this is enforced in code. One early probe was discarded on exactly that basis; it is retained in [`evidence/superseded/`](evidence/superseded/) with the reason recorded. **Its record hash was not recomputed to make it verify.** A chain that can be rewritten to fit proves nothing.

---

## Reproduce it

Every classification regenerates from the append-only evidence log alone. Nothing is hand-entered.

```bash
pip install -e .
python -m keyring authority          # rebuild the authority map from evidence
python -m keyring least-privilege    # diff the manifest against the measurement
python -m keyring financial-reach    # layered capital view
python -m keyring validate-config    # config checksums
python -m pytest -q                  # full suite
```

Raw responses are in [`evidence/raw/`](evidence/raw/), verbatim and hash-chained, with credential-shaped values redacted. The full experimental record is in [`docs/m0.md`](docs/m0.md); the findings are in [`docs/findings.md`](docs/findings.md).

---

## Limits

**INCONCLUSIVE:** Six of seven supported clients are unmeasured. No claim that protection varies *between clients* is published.

**INCONCLUSIVE:** No `ADVERTISED_ONLY` case, and no `-2015` response, so the DOCUMENTED ambiguity of that code remains untested here.

**INCONCLUSIVE:** Run C found no eligibility-level denial. This account is eligible for every product its grant covers, so the granted-versus-effective gap does not appear at the eligibility layer in this configuration. An account without futures enabled would be needed.

**INCONCLUSIVE:** Whether a different client permission mode, or a larger or fillable order, would produce a confirmation prompt. Untested.

**ASSUMED:** That `wallet.getApiKeyPermission` not reflecting OAuth scope is a legacy-endpoint artefact.

**OBSERVED:** Two results rest on an operator observing a screen rather than a captured response — the permission screen having no toggles, and the client showing no prompt. Both are labelled as such in the evidence log.

**OBSERVED:** All probing ran from a GB egress address. The prober was never hosted on a US IP.

---

## Safety

**DOCUMENTED (Binance security guidance, repeated here as instructed):** never paste the MCP endpoint into an AI chat and ask it to install the server, and never open the endpoint directly in a browser.

**OBSERVED:** This build honours both. Sessions are obtained only by authorizing through a client Binance documents as supported.

**OBSERVED:** The audit runs on an empty Agentic sub-account. Every balance was zero throughout. Capability was measured before any money was at risk.

**OBSERVED:** Rate limiting is a safety invariant enforced in code: one probe per capability, a hard per-run and per-minute budget, `429` backs off honouring `Retry-After`, `418` stops the run outright, `403` halts, and `5xx` is recorded INCONCLUSIVE rather than retried. No `429`, `418` or `403` was received during this audit.
