# Submission readiness audit

Audited against the repository at `main` and the official Binance materials on
8 September 2026. This document separates published requirements from an
engineering-quality review; Binance has not published a scored judging rubric
in the official hackathon announcement.

## Official Track A / Track 1 requirements

| Requirement | Repository status | Evidence / action |
|---|---|---|
| Build an AI agent with Binance Agent OS | **PASS** | `KeyringAgent` plans tests from Binance MCP runtime schemas and live filters. Binance identifies MCP as an Agent OS building block and supports self-built agents. |
| Video or demo | **ACTION REQUIRED** | The retained-evidence dashboard and `docs/demo-script.md` are ready; the final video file or public video link is not in the repository. |
| GitHub repository | **PASS locally** | The project is committed on `main`; confirm the submission URL is public from a signed-out browser. |
| Follow/repost, reply or quote-repost, and survey | **EXTERNAL ACTION** | These are submission-account actions and cannot be proved by the codebase. |
| Participant and jurisdiction eligibility | **EXTERNAL DETERMINATION** | Binance determines eligibility through the submission process. Static `egress_country` harness metadata is not participant-location evidence. |

Official sources: [hackathon announcement](https://www.binance.com/en/square/post/362885563835358),
[Agent OS overview](https://www.binance.com/en/agent-os), and
[Agent OS introduction](https://www.binance.com/en/blog/ecosystem/5991233187660196794).

## Competitive-quality review

Because no official scored rubric is published, these are review dimensions,
not Binance criteria.

| Dimension | Assessment | Why |
|---|---|---|
| Clear problem | **STRONG** | Permission UI, credential self-report, discovered tools, and measured behavior can disagree; KEYRING reconciles them. |
| Necessary agent behavior | **STRONG** | Runtime schemas and symbol filters vary. The model performs bounded planning where static hard-coding is brittle. |
| Safety | **STRONG** | The model has no Binance client; deterministic validation, budgets, connection checks, and state comparisons surround each authority test. |
| Technical execution | **STRONG** | Typed Python package, verified evidence replay, provenance-safe capital/gate joins, read-only dashboard, and automated tests. |
| Evidence quality | **STRONG** | Conclusions resolve to JSONL records; active chains verify; historical records are not rewritten to fit later schemas. |
| Originality | **STRONG** | This is an agent that audits other financial-agent permissions rather than another trading strategy. |
| User experience | **GOOD** | The dashboard explains the disagreement in plain language and expands into proof. A public demo URL would remove local setup friction. |
| Reproducibility | **GOOD WITH BOUNDARY** | Saved evidence fully reproduces analysis. Repeating the authenticated measurement requires a fresh authorized Agent OS session and is intentionally not part of the demo. |
| Submission completeness | **BLOCKED BY VIDEO/DEMO LINK** | Code, evidence, tests, and script are present. The required public-facing video or demo artifact still needs to be attached to the submission. |

## Code-quality checks

The repository CI runs four independent gates:

```text
compile → static type check → security scan → full test suite
```

The local audit also checks that no credential-shaped value is present in
tracked evidence. The dashboard exposes no write endpoint and renders only safe
record summaries, not raw credential-bearing payloads.

## Submission checklist

- Record and publish the three-minute video from retained evidence; do not run a
  live trade or reconnect for the recording.
- Confirm the GitHub repository and video/dashboard URL work in a signed-out
  browser.
- Put the hook in the submission post: **same permission set, same measured
  trading surface, different self-report**.
- State that the finding is an observability gap, not a vulnerability.
- Follow and repost the Binance announcement, reply or quote-repost with the
  video/demo and GitHub link, then complete the survey before the deadline.
- Confirm participant eligibility directly in Binance's submission flow.

## Non-blocking product notes

- No software license is currently declared. This does not change the measured
  result, but adding one later would make reuse terms explicit.
- The evidence hash chain is tamper-evident but has no external timestamp or
  signature anchor; do not describe it as proof of authorship.
- `evidence/state-chain.json` is a legacy summary. The product regenerates the
  current state view from `evidence/raw/`; do not use the legacy file in the
  demo.
