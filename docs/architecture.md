# Architecture

**OBSERVED:** The local implementation follows this evidence flow:

```text
checksummed config
      ↓
discovery capture + safety-wrapped session transport
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

**OBSERVED:** The authenticated Agentic tool surface and JSON-RPC response envelope are captured in [`evidence/raw/0003-m0-tools-list.jsonl`](../evidence/raw/0003-m0-tools-list.jsonl). The measured probe path is implemented by `McpClient`: read-shaped calls use `call_tool`, write-shaped calls are refused there, and an explicit budgeted `probe()` call is required for a probe.

**OBSERVED:** `capture-tools` remains discovery-only and never invokes a tool. The live probe path is separate, records the raw `tools/call` response, and is constrained by the positive control, complete state snapshots, probe budget, and rate-limit halts.

**OBSERVED:** The classifier consumes evidence records rather than dashboard input. A missing control, missing state proof, ambiguous response, rate-limit halt, or server error remains `INCONCLUSIVE`.
