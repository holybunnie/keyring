# Evidence format

**OBSERVED:** Runtime evidence is JSON Lines under `evidence/raw/`. Each line is a validated `EvidenceRecord`.

**OBSERVED:** The writer appends a sequence number, the previous-record hash, and a record hash. Loading the log verifies sequence continuity and the complete hash chain before analysis.

**OBSERVED:** Raw responses are retained in `raw_response` after credential-shaped values are redacted. Request and response mappings are recursively redacted for authorization, token, secret, signature, cookie, password, and API-key-shaped keys.

**OBSERVED:** The authority map is derived from the evidence records. A capability is **VERIFIED** only when its positive control passes, its controlled probe reaches a recorded validation response, and complete before/after state snapshots compare equal. A capability with no write tool in the captured surface is **DENIED** at discovery.

**OBSERVED:** The authenticated Agentic `tools/list` response and JSON-RPC envelope are retained as raw evidence. `capture-tools` performs discovery only; it does not invoke an MCP tool or create financial state.

**OBSERVED:** The dashboard, authority map, least-privilege diff, and financial-reach view are rebuilt from the verified evidence log. No result is hand-entered.
