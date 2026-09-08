# Architecture

**OBSERVED · harness:** The local implementation follows this evidence flow:

```text
checksummed config
      ↓
discovery capture + safety-wrapped session transport
      ↓
runtime schema/filter snapshot
      ↓
agent proposal (model or static) → deterministic non-execution gate
      ↓
connection check
      ↓
one safe test per capability
      ↓
before/after state snapshots
      ↓
append-only raw evidence
      ↓
deterministic classification ← optional model interpretation of unmatched responses
      ↓
permission trace
      ↓
reach, strategy diff, provenance-keyed capital layers
      ↓
read-only dashboard
```

**OBSERVED · harness:** The authenticated Agentic tool surface and JSON-RPC response envelope are captured in [`evidence/raw/0003-m0-tools-list.jsonl`](../evidence/raw/0003-m0-tools-list.jsonl). The measured test path is implemented by `McpClient`: read-shaped calls use `call_tool`, write-shaped calls are refused there, and an explicit budgeted `probe()` call is required for a test.

**OBSERVED · harness:** `capture-tools` remains discovery-only and never invokes a tool. The live test path is separate, records the raw `tools/call` response, and is constrained by the connection check, complete state snapshots, probe budget, and rate-limit halts.

**OBSERVED · harness:** The classifier consumes evidence records rather than dashboard input, so every displayed classification has a raw evidence source and proof chain.

**OBSERVED · harness:** The agent boundary is deliberately narrow. The model sees runtime tool schemas, live filters, capability context, and prior test history only to propose a safe test. A deterministic validator rejects any proposal that is not tied to a discovered write tool or that does not violate a live rejection filter. The model never receives a Binance client.

**OBSERVED · harness:** `agent-replay` exposes the complete recorded loop without
opening a network connection or changing evidence. It verifies the retained
chains, resolves the recorded runtime schema and symbol filters by run and
capability, recomputes the deterministic gate from those exact inputs, and
shows the recorded request, response, model interpretation, final result, and
state proof with source references.

**OBSERVED · harness:** For an unmatched gateway response, the model may propose a class and reason. The deterministic classifier remains authoritative; known codes never enter the model path, and disagreements remain in the evidence record.

**OBSERVED · harness:** Gate observations and capital views are keyed by account, client, and permission mode. A balance from one account or client cannot silently supply the gate or risk statement for another; the dashboard renders each compatible context separately.
