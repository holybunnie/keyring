# Architecture

**OBSERVED:** The local implementation follows this evidence flow:

```text
checksummed config
      ↓
discovery-only session transport
      ↓
positive control
      ↓
one non-executing probe per capability
      ↓
before/after state snapshots
      ↓
append-only raw evidence
      ↓
derived classification and proof chain
      ↓
reach, strategy diff, capital layers, revocation summary
      ↓
read-only dashboard
```

**ASSUMED:** The exact Agentic tool names and the gateway's response envelope remain unresolved until an authenticated `tools/list` capture exists. The repository therefore does not pretend to have a live prober adapter.

**OBSERVED:** `capture-tools` stops after discovery. The generic transport rejects `tools/call`; a future adapter must be added only after the captured surface and M0 execution path are understood.

**OBSERVED:** The classifier consumes evidence records rather than dashboard input. A missing control, missing state proof, ambiguous response, rate-limit halt, or server error remains `INCONCLUSIVE`.
