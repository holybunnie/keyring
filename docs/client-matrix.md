# The client matrix

> Same grant. Same sub-account. Same probe. Seven clients.
>
> Authority is a property of the grant. The gate is a property of the client.

## Why this grid is the submission

**OBSERVED:** A spot order invoked directly against the gateway with a valid session token reached Binance's order validation with no confirmation step (see [`findings.md`](findings.md)).

**ASSUMED:** Therefore the confirm-before-execute pattern DOCUMENTED for "every non-read action" is enforced by the client application rather than by the gateway. This build has not inspected any client's implementation, so the location of the control is inferred, not established. **The grid is the experiment that would establish it.**

If the grid comes back as predicted, one image says: *same credential, same money, different protection, and nothing on any screen discloses which you are getting.*

**The grid must be allowed to disagree with that prediction.** "Authority will be identical everywhere" is a hypothesis, not an observation, and is recorded here as ASSUMED until seven rows exist.

## What can and cannot be measured from the build environment

| Column | Evidence source | Can this build produce it? |
|---|---|---|
| Granted scope | credential store / gateway | **Yes** — programmatic |
| Advertised tool surface | `tools/list` | **Yes** — programmatic |
| Probe result and error code | `tools/call` | **Yes** — programmatic |
| State proof | snapshot chain | **Yes** — programmatic |
| **Whether a confirmation gate fires** | **the client's own interface** | **No** |
| **Where the gate is enforced** | **the client's own interface** | **No** |

**OBSERVED:** The build environment is a headless Linux container with no display. Claude Desktop, ChatGPT on the web, ChatGPT/Codex Desktop, VS Code and Grok Bot are graphical applications that cannot be installed, run or observed from it.

**OBSERVED:** Whether a confirmation dialog appears is a visual event in a client's interface. It does not appear in any gateway response, so no amount of programmatic capture can substitute for a human watching the screen.

**Consequently the gate column is a human observation with a screenshot, for all seven rows including the two clients that are installed here.** This is stated plainly rather than being quietly filled with inference.

## Protocol — run once per client

Each row is produced by the same fixed procedure, so the rows are comparable.

1. Connect the client to `https://agent.binance.com/mcp/agentic`, selecting **the existing Agentic sub-account** — not a new one. A different sub-account invalidates the comparison.
2. At the consent screen enable exactly: **Read agentic account and market data**, **Spot & Margin trading**, **Futures trading**. Leave master-account read, margin loan, and internal transfer **off**.
3. Record the granted scope. From this repository: `python -c "import sys;sys.path.insert(0,'src');from keyring.session import load;print(load().metadata())"`
4. Ask the client, in its own interface, to place this order:
   **buy 0.00001 BTC at a limit price of 0.01 USDT on BTCUSDT.**
   This is the same probe the audit uses. It is rejected by Binance's price filter before the matching engine, and the account holds no funds.
5. **Record what happens before anything is sent**, with a screenshot:
   - Did a confirmation prompt appear? Yes / No
   - Did it show the order parameters?
   - Was approval required, or was there only a cancel option?
6. Record the final result the client reports.
7. Re-run the state chain and confirm it still hashes to one distinct state.

## The grid

`GATE` = did the client require human approval before the call reached Binance.

| # | Client | Granted scope | Advertised write tools | Probe result | GATE | Evidence |
|---|---|---|---|---|---|---|
| 1 | **Direct gateway call** (no client) | `mcp:account:read mcp:futures:trade mcp:spot:trade` | 11 | `-1013` filter failure | **NONE — OBSERVED** | `evidence/raw/0007` |
| 2 | **Claude Code**, default mode | `mcp:account:read mcp:futures:trade mcp:spot:trade` | 11 | ran; no prompt | **NONE — OBSERVED** | `evidence/raw/0010` |
| 2b | **Claude Code**, `--permission-mode manual` | same credential | 11 | asked first; operator declined | **CLIENT — OBSERVED** | `evidence/raw/0010` |
| 3 | Claude Desktop | — | — | — | **NOT OBSERVED** | — |
| 4 | Codex CLI | — | — | — | **NOT OBSERVED** | — |
| 5 | ChatGPT on the web | — | — | — | **NOT OBSERVED** | — |
| 6 | ChatGPT / Codex Desktop | — | — | — | **NOT OBSERVED** | — |
| 7 | VS Code | — | — | — | **NOT OBSERVED** | — |
| 8 | Grok Bot | — | — | — | **NOT OBSERVED** | — |

**OBSERVED:** Row 1 is the control, and it is the only row this build produced. It establishes that the gateway itself does not gate: a token holder reaches order validation with no approval step.

**Row 1 is not a client.** It is the baseline the seven clients are measured against. A client whose gate column reads NONE is behaving like row 1.

**OBSERVED — row 2.** Claude Code, a DOCUMENTED supported client, invoked `spot.newOrder` with **no confirmation prompt**. The operator was not asked to approve anything.

**OBSERVED:** No `allowedTools` entries and no `defaultMode` override were configured for this project, so the client was running its default permission mode. This is out-of-the-box behaviour, not a setting the operator had weakened.

**OBSERVED — row 2b.** The same client, same credential and same order under `--permission-mode manual` **did** ask before invoking. The only variable changed was the client's permission mode.

**OBSERVED:** Rows 2 and 2b together show the confirmation is a client-side setting whose default is permissive, rather than a property of the gateway.

**INCONCLUSIVE:** Rows 3 through 8 are unfilled. Two rows now exist, but row 1 is the gateway baseline rather than a client, so **no claim that protection varies *between clients* may be published.** What rows 1 and 2 jointly support is stated below.

## Honest statement of scope for the submission

**OBSERVED:** One configuration was measured end to end: a session authorized through Claude Code, a DOCUMENTED supported client, invoked directly against the gateway.

**ASSUMED:** That the other six supported clients present the same authority. Untested.

If the grid stays unfilled, the claim that survives is the narrow one, and it is still worth publishing:

> The gateway does not require confirmation. Any confirmation a user sees is added by their client, and in the one supported client measured here, running its default settings, none was added.

**OBSERVED:** The DOCUMENTED statement that every trade is *"Confirmed by you first"* was not observed in the tested configuration. It is not contradicted as a statement of intent, and no claim is made about other clients or other permission modes — but a user of this supported client, at its defaults, received no confirmation step.

**ASSUMED:** That the confirmation is therefore a client-side and client-configuration-side property rather than a gateway property. Two observations support it; six clients remain unmeasured.
