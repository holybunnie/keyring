# Evidence format

**OBSERVED · harness:** Runtime evidence is JSON Lines under `evidence/raw/`. Each line is a validated `EvidenceRecord`.

**OBSERVED · harness:** The writer appends a sequence number, the previous-record hash, and a record hash. Loading the log verifies sequence continuity and the complete hash chain before analysis.

**OBSERVED · harness:** Raw responses are retained in `raw_response` after credential-shaped values are redacted. Request and response mappings are recursively redacted for authorization, token, secret, signature, cookie, password, and API-key-shaped keys.

**OBSERVED · harness:** The authority map is derived from the evidence records. A capability is **VERIFIED** only when the connection check passes, its controlled test reaches a recorded validation response, and complete before/after state snapshots compare equal. A capability with no write tool in the captured surface is **DENIED** at discovery.

**OBSERVED · harness:** The authenticated Agentic `tools/list` response and JSON-RPC envelope are retained as raw evidence. `capture-tools` performs discovery only; it does not invoke an MCP tool or create financial state.

**OBSERVED · harness:** The dashboard, authority map, least-privilege diff, and financial-reach view are rebuilt from the verified evidence log. No result is hand-entered.

## Agent evidence boundary

**OBSERVED · harness:** New test records carry `planned_by` (`model` or `static`) and `probe_justification`. A model proposal, when present, is stored separately from the deterministic validation result.

**OBSERVED · harness:** The model adapter is text-only. It has no Binance client and cannot invoke MCP tools. The deterministic proposal validator requires a discovered write tool, the requested symbol, complete schema arguments, a positive notional below the live `MIN_NOTIONAL` or `NOTIONAL` threshold, and a non-empty justification before the test path is entered.

**OBSERVED · harness:** Known response codes are classified without a model. Only an unmatched response may be sent to the optional model interpreter. The evidence retains the model proposal, final deterministic classification, and disagreement flag; the model cannot change the final class.

**OBSERVED · operator:** A person-watched observation is labelled separately from a harness-captured response. The dashboard renders these as `OBSERVED · operator` and `OBSERVED · harness`.

Historical records omit these new optional fields and retain their original hashes. They are not retroactively labelled as model-planned.
