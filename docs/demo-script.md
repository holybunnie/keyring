# Demo script

This script uses only retained evidence from `evidence/raw/`. It does not call
Binance live and does not require reconnecting the measured accounts.

## 0:00 — hook

**OBSERVED · harness:** “We connected an AI agent to two Binance accounts, then
checked four different ways what each connection could do. The answers did not
match.”

## 0:15 — the headline panel

**OBSERVED · harness:** “On Account A, the permission screen said Spot & Margin
trading and Futures. Binance's own permission check reported Spot and Futures
trading disabled. The tools handed to the agent included eleven trading writes,
and controlled tests confirmed Spot, USDⓈ-M Futures, and COIN-M Futures.”

**OBSERVED · harness:** “Account B had the same 71-tool, eleven-write measured
surface and the same three confirmed trading families. Binance's own permission
check reported Spot and Futures enabled. Same permission set. Same measured
trading surface. Different self-report.”

## 1:05 — what the difference means

**OBSERVED · harness:** “This is not reported as a security hole. It is an audit
answer that does not describe the connected session consistently. KEYRING keeps
the observation and does not guess at its cause.”

## 1:20 — confirmation behaviour

**OBSERVED · operator:** “Claude Code's default path reached validation without a
prompt. Its manual mode showed a prompt, and the operator declined. Codex CLI's
default mode showed a prompt before its dispatcher stopped before Binance
validation. Whether a prompt appeared before validation depended on client and
mode. Whether Binance confirms after validation and before execution was not
measured.”

## 1:40 — the agent, from the recorded run

**OBSERVED · harness:** Show the retained trace: runtime schema and live filters
→ model proposal with justification → deterministic non-execution gate →
safety-wrapped request → Binance response → unchanged state.

“The agent designs the test from the runtime schema and live filters. The model
proposes; deterministic code checks the proposal before the harness sends it,
and deterministic code owns the result. The active record `0012#78` preserves a
model suggestion of `VERIFIED` beside the deterministic `INCONCLUSIVE` result.”

## 2:00 — what the authority was worth

**OBSERVED · harness:** “On the funded Account B, the dashboard displays 5.59
USDT reachable through confirmed trading paths. The exact retained balance is
5.58854065 USDT. Codex CLI showed a prompt before dispatch, so autonomous
capital at risk in that client context was 0.”

## 2:18 — access removal

**OBSERVED · operator:** “In the recorded trial, five reads were permitted. After
the operator disconnected the agent, the next recorded read returned `Auth
required`. This is n=1. The 20.680-second figure is the interval between
recorded observations, not UI-click-to-denial latency.”

## 2:33 — the proof

**OBSERVED · harness:** Open an authority row and its evidence chips. “Every
authority test has a complete before-and-after account-state check. The evidence
log is replayed to rebuild the page; every figure links back to a record.”

## 2:48 — close

**OBSERVED · harness:** “KEYRING did not find hidden trading tools or weak
enforcement. It found the same measured trading surface described differently
by different first-party views. That is why it measures authority instead of
inferring it.”
