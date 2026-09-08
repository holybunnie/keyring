# Audit: KEYRING

> **Remediation update — 8 September 2026:** This file preserves the initial
> adversarial findings below. The current worktree has fixed the two
> presentation-integrity defects, corrected the client-matrix value, moved the
> agent to the front of the README, and added a read-only `agent-replay` CLI
> path for the retained runtime-schema → model plan → deterministic gate →
> recorded request loop. Operator observations now render explicitly as
> `OBSERVED · operator`, and opposite client defaults remain separate instead
> of being resolved by filename order. The missing public demo/video remains
> the only hard submission blocker. Findings 3, 4 (for non-probe capture
> types), and 6–10 remain post-submission quality work.

I verified the claims independently rather than trusting the repo's own tooling — re-computed all 14 raw evidence chains with my own SHA-256 script, ran the suite, ran every documented command, and read the raw JSONL behind each headline number.

**Two things ahead of the code review, because they outrank it.** The Agent OS Mini Hackathon closes **today, 8 Sept 2026 at 23:59 UTC** — under ten hours from now — and its stated submission requirement is a **demo or video + GitHub repo + survey**. There is no video in this repo; `docs/demo-script.md` is a script, not a recording. Separately, 20 records across 8 evidence files stamp `"egress_country":"GB"`, and the UK is one of the restricted jurisdictions for this hackathon. Details in the last section.

---

## What holds up

The evidence is real. Genuine Binance order IDs (`66360642090`, `66360648340`), real fills at `78323.20`, real `-1013 / -4013 / -1111` rejections, real `Binance-MCP-Server 1.1.0` envelopes. 90 MB of captured JSONL, not fixtures.

- **All 14 raw chains verify** under my own hasher. The one file that fails (`superseded/0006`) fails *deliberately* and is documented as such — "A chain that can be rewritten to fit proves nothing." That single choice does more for your credibility than the rest of the README.
- **101 tests pass.** `tests/test_published_numbers.py` recomputes README figures from evidence and fails on drift, and shells out to every documented command. I've rarely seen a hackathon build police its own writeup in CI.
- **The model-boundary claim is true.** `interpreter.py:35` sets `final_classification = classifier_decision` unconditionally. The one real disagreement (`0012#78` — model proposed VERIFIED, classifier said INCONCLUSIVE) is preserved verbatim in the record. You claimed a hard boundary and you actually built one.
- **`planner.validate_proposal` is a real gate**, not theatre: notional must be below the live MIN_NOTIONAL *and* a named live filter must actually be violated.
- **`keyring trace` resolves every classification line to `file#line`.** That's the strongest artifact here.
- The dashboard degrades honestly on an empty evidence dir instead of crashing or inventing.

Finding 1 is genuinely interesting and genuinely evidenced: `enableSpotAndMarginTrading: false` on the original account while three write paths reached Binance order validation in the same session.

---

## What doesn't

**1. Last-write-wins flips your headline number.** `dashboard.py:157-160` and `financialreach.py:144-163` both loop over sorted evidence files and keep the *last* non-manual `client_gate_observation`. There are exactly two:

```
0010-client-matrix.jsonl:1    gate=UNGATED       Claude Code, default mode
0012-codex-cli-second-account.jsonl:141  gate=CLIENT-GATED  Codex CLI, default mode
```

Filename sort puts Codex last. So the dashboard publishes *"Is a confirmation always shown before an action? → **Confirmation shown in the tested default**"* and `financial-reach` publishes *"Autonomous capital at risk **0**"* — both flatly contradicting your own README Finding 3 and `docs/client-matrix.md`. Your demo-facing artifact reports the reassuring half of the finding the project exists to surface, and which half wins is decided by a filename. This is the one that would sink you with a sharp judge. Report per-client, or take the worst observed default — never last-seen.

**2. Finding 3 rests on operator testimony wearing the OBSERVED label.** The `0010` records carry `captured_by_build: false`, `screenshot_captured: false`, `evidence_type: "operator observation of a client interface"`. The README table prints that row beside a machine-captured gateway row with no distinction. Your label scheme is the build's spine; it needs a fourth label (REPORTED) or an inline caveat.

**3. The revocation section is hand-transcribed.** `revocation.py:13` says so — "manually recorded." `0017`'s timestamps are millisecond-rounded, unlike every machine-captured file, and its own metadata says `poll_interval_seconds: 1` while the actual gaps are 14s, 9s, 84s, 3s, 21s. The README says the click "was not timestamped inside the poller," implying a poller ran. n=1 is disclosed; the transcription isn't.

**4. The capture harness is not in the repo.** `src/` writes only `capability_probe`, `positive_control`, `probe`, `state_component`, `tools_list`, `m0_preflight`. The evidence contains 13 more types — `transaction`, `order_book_walk`, `financial_balance_quote`, `revocation_check`, `permission_report`, `market_data`, `instrument_inventory`, `session`, `mcp_discovery`, `symbol_filters`, `operator_observation`, `account_snapshot`, `initialize` — with **no producer anywhere in the codebase**. "Reproduce it" reproduces the *analysis*, not the *measurement*. Financial reach and revocation cannot be re-run or method-audited by a judge. Separately: `SafeProbeRunner` — your most polished safety code — produced **zero** shipped records.

**5. `docs/client-matrix.md:11` contradicts the raw evidence.** It says the probe was "at `1.00` USDT"; `0007#30` sends `price: "0.01"`, matching README and m0. `test_published_numbers.py` guards README only — extend it to `docs/`.

**6. The hash chain is self-sealed.** `evidence.py:_hash_payload` — anyone editing a record recomputes the chain in one pass. It detects corruption, not authorship; there's no external anchor. Your superseded README states the principle correctly, then `evidence/raw/` doesn't meet it. Say so in the README instead of letting a judge find it.

**7. `evidence/state-chain.json` is a stale orphan** — 4 snapshots / 1 distinct state, versus the published 18 / 7. No code or doc references it. Delete or regenerate.

**8. `-1100` was added to `PARAMETER_REJECTION_CODES` after the model argued for it** (`prober.py:47`). The disagreement is honestly preserved and the rule is applied uniformly — but the classification path was widened post-hoc to match an outcome. That deserves a sentence, not silence.

**9. Framing that's generous to itself.** "Zero-state proof" and "No exploits. Explicitly approved measurement" sit above numbers produced by a run that placed two real market orders. It *is* disclosed — but "Binance retained `0.00000993 BTC` as below-minimum-lot dust" is wrong: you bought `0.00007`, paid `0.00000007` commission, and sold only `0.00006` because LOT_SIZE step is `0.00001`. Binance retained nothing; that residue is your own sell-sizing rounding.

**10. Minor:** `margin.queryMarginAccountsOpenOrders` returns `-3003 This account does not exist` on every single capture, yet counts as one of the "fourteen state components." And the `1,362` instrument figure isn't re-derivable — the 37 MB response was dropped for size, keeping only a SHA-256 (disclosed in the record, not in the README).

---

## Honest verdict

This is a real measurement project with an unusually disciplined evidence spine, and it is undermined by its own presentation layer. The engineering that matters — chain verification, deterministic classification, the model gate, the README-vs-evidence test — is better than the writeup. The two things a judge would actually check first (the dashboard headline and "autonomous capital at risk") are the two things that currently misreport your own strongest finding.

Roughly: evidence quality **A−**, intellectual honesty **A−** (the superseded-file discipline is exceptional; the operator-observation labelling and the missing capture harness are the gaps), engineering **B+**, headline consistency **C**. Fix #1 and #2 and it's a coherent submission; leave #1 in and a careful reviewer finds it in five minutes and doubts everything else.

---

## Against the Agent OS Mini Hackathon — Track A

**Track A fit is legitimate, and stronger than it first looks.** This is built on Agent OS: `https://agent.binance.com/mcp/agentic` appears as the source in 12 evidence records, plus 3 OAuth discovery records against `agent.binance.com/.well-known/`. And there *is* a real agent — `src/keyring/agent.py`, `KeyringAgent` — running a genuine loop:

```
runtime tools/list + live symbol filters
   → Claude proposes a probe (tool, arguments, expected filter, justification)
   → deterministic gate (planner.validate_proposal) accepts or rejects
   → safety-wrapped execution (positive control, state snapshot, budget)
   → Claude interprets any unmatched response
   → deterministic classifier owns the published class
```

It ran live: 4 model-planned probes and 2 model interpretations in `0012-codex-cli-second-account.jsonl`, each carrying `planned_by: model` and the model's full reasoning in the record.

That is an unusual and genuinely interesting agent design, and it's the strongest Track A story you have: **an agent that plans real trading actions against live exchange filters and is structurally incapable of executing one.** Most Track A entries will be agents that can move money and hope they don't. Yours provably can't, and the proof is in the evidence chain.

### The problem: your submission hides its own agent

**1. The README frames the agent as a disclaimer.** Your "Model boundary" section leads with what the model *doesn't* do — "the model never receives a Binance client," "No classification, no published number, no financial figure and no verdict in this repository is produced by a model." For a track literally named *build an AI agent with Agent OS*, your most prominent statement about the model is how little it does. That's a positioning problem, not a build problem, and it's fixable tonight in prose. The gate is the feature — say it that way round.

**2. The documented path never runs the agent.** Your "Reproduce it" block — `authority`, `trace`, `least-privilege`, `financial-reach`, `validate-config`, `dashboard`, `pytest` — makes **zero model calls**. `plan-probe` and `interpret-response` appear as opt-in flags in a following paragraph. A judge who runs your README top to bottom sees an evidence-analysis tool and never once sees the agent think. On an agent track, that's the highest-cost sentence in the repo.

**3. REMEDIATED.** `agent-replay` now reconstructs the complete retained cycle
from verified evidence, recomputes the gate from the exact recorded schema,
filters, and proposal, and shows the recorded request, interpretation,
deterministic result, and state proof without reconnecting or mutating evidence.

**4. Thin agent track record.** 6 of 329 evidence records involve the model, all in a single file. Every other probe was statically planned. For an agent-track submission, the agent's own demonstrated history is slim.

### How it reads to a Track A judge

| Dimension | Read | Why |
|---|---|---|
| Built on Agent OS | **Yes, verifiably** | 12 records against the agentic MCP endpoint, plus OAuth discovery; two grants, two sub-accounts, two clients |
| Agent design | **Very strong, and original** | A plan→gate→act→interpret loop where the gate is deterministic and the model provably cannot execute. Nobody else will submit this |
| Rigor / evidence | **Best-in-class** | Chain verification, the README-vs-evidence test, and keeping a failing superseded record rather than re-sealing it beat most production security work |
| Usefulness to Binance | **Strong** | A reproducible observability gap in their own `wallet.getApiKeyPermission` self-report, with raw responses attached |
| Technical execution | **Good, with a real dent** | Defect #1 above is exactly the class of bug this project exists to catch |
| Discoverability of the agent | **The weak link** | No CLI path to the full loop, no model call in the documented commands, and a writeup that downplays it |
| Presentation / demo | **Blocking** | No video exists, and the dashboard headline contradicts your own central finding |

**One strategic note, not a criticism.** Your headline finding is a gap in Binance's own consent surface, submitted to a Binance-run hackathon. Your framing already handles this correctly — "an observability gap, not a vulnerability," "Enforcement was not shown to be weak," and no exploit anywhere. Keep that exactly as it is in the video. The build is more impressive *because* it declines to overclaim, and a judge from the team that owns that endpoint will notice the restraint.

### If you're submitting tonight, in this order

1. **Record the demo.** It's a hard submission requirement and you have none. Lead with the agent loop, not the evidence tooling.
2. **Run `agent-replay` in the demo.** It exposes the complete retained loop
   without creating a new measurement.
3. **Fix defect #1** (last-write-wins gate selection). Small change, and it's the thing that most undermines the video you're about to record.
4. **Rewrite "Model boundary" as "The agent."** Same facts, inverted emphasis.

Everything else in this document can wait for a post-deadline commit.

---

*Corrections on my earlier passes: I first scored this against the Arkiv Ideathon rubric — the only rubric-bearing tool connected to this session, and the wrong event entirely. I then read the build as a Track B ("connect your MCPs and trade") entry. It's Track A, and having read `src/keyring/agent.py`, Track A is the better fit on the merits, not just by your choice of lane.*
