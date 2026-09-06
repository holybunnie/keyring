# Evidence format

**OBSERVED:** Runtime evidence is JSON Lines under `evidence/raw/`. Each line is a validated `EvidenceRecord`.

**OBSERVED:** The writer appends a sequence number, previous-record hash, and record hash. Loading the log verifies sequence continuity and the complete hash chain before classification.

**OBSERVED:** Raw responses are retained in `raw_response` after credential-shaped values are redacted. Request and response mappings are recursively redacted for authorization, token, secret, signature, cookie, password, and API-key-shaped keys.

**OBSERVED:** Classifications are derived from records. The classifier recognizes `VERIFIED` only when a positive control passes, the downstream validation error is `-1013`, and complete before/after snapshots compare equal. It recognizes `DENIED` only for `-2015` with the same control and state proof. Other responses remain `INCONCLUSIVE` unless an explicit `advertised_only` outcome is recorded.

**ASSUMED:** The exact JSON-RPC envelope and tool names exposed by a live Binance Agentic session are not known until an authenticated `tools/list` response is captured. The transport client therefore exposes only generic request and `tools/list` methods and never invents a tool surface.
