# Demo script

This script narrates the measured KEYRING build. All values come from `evidence/raw/`.

## 0:00 — boundary

**OBSERVED:** “KEYRING performs zero-state-change auditing. It cannot trade or transfer. Every probe is bounded by before/after state proof and rate limits.”

**DOCUMENTED:** “Binance says not to paste the MCP endpoint into an AI chat or open it directly in a browser. The build follows that guidance.”

## 0:20 — grant and discovery

**OBSERVED:** “The same Agentic sub-account was measured under an Account grant and an Account plus Trade grant. The advertised surface changed from 60 read tools to 71 tools with eleven write tools.”

## 1:00 — authority trace

**OBSERVED:** “Each authority row expands to its positive control, probe response, and unchanged state proof. Spot, USDⓈ-M Futures, and COIN-M Futures reached validation and were classified VERIFIED. Margin, Convert, and Transfer had no write tool advertised and were classified DENIED at discovery.”

## 1:30 — client gate

**OBSERVED:** “The direct gateway baseline and Claude Code default mode reached Spot validation without a confirmation. Claude Code manual mode and Codex CLI default mode displayed a prompt.”

## 2:00 — least privilege

**OBSERVED:** “The manifest needs Spot for BTCUSDT and ETHUSDT. The measured grant also verified both futures families, exposing eight measured excess write tools. Narrowing requires disconnecting and re-authorizing.”

## 2:30 — financial reach and proof

**OBSERVED:** “After capability measurement, the second sub-account was funded separately. The fresh read-only snapshot shows 5.6 USDT visible and 5.6 USDT reachable through verified trading paths. Codex CLI default mode displayed a confirmation prompt, so autonomous capital at risk is 0 for that tested default.”

**OBSERVED:** “Fourteen state components were captured before and after the current probes. The aggregate evidence replays 268 records with 15 state digests, four distinct captured states, identical before-and-after probe pairs, and an unbroken hash chain.”

## Close

**OBSERVED:** “KEYRING turns a consent grant into a replayable authority map: what the session advertised, what it reached, what the client asked the user to approve, and whether financial state changed.”
