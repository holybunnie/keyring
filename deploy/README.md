# Public dashboard deployment

The production dashboard serves a generated, read-only state artifact so a
request does not need to replay the large retained evidence corpus. The artifact
is never prepared manually.

From the repository root, build it through the same trusted derivation path as
the live dashboard:

```bash
python -m keyring build-dashboard-state \
  --evidence evidence/raw \
  --output state/dashboard.json
```

The command verifies every active JSONL evidence chain, derives the complete
dashboard state, records SHA-256 hashes for every evidence source and the
strategy, writes a deterministic JSON envelope atomically, and refuses to write
a degraded report. At server startup, KEYRING verifies the state digest and
checks the complete source manifest before accepting the artifact.

## Host setup

1. Install the project into `/home/ubuntu/keyring/.venv`.
2. Generate `/home/ubuntu/keyring/state/dashboard.json` with the command above.
3. Replace every `dashboard.keyring.example` occurrence in
   `deploy/keyring-nginx.conf` with the public hostname.
4. Point that hostname's DNS record at the host.
5. Obtain a Let's Encrypt certificate for the hostname.
6. Install `deploy/keyring.service` under `/etc/systemd/system/` and the nginx
   file under `/etc/nginx/sites-enabled/`.
7. Validate nginx, start KEYRING, reload nginx, and verify the URL from a
   signed-out browser.

The Python server binds only to `127.0.0.1:8081`. Nginx redirects HTTP to HTTPS,
terminates TLS, adds restrictive browser headers, and proxies read-only requests
to KEYRING.

Whenever retained evidence or `config/strategy.yaml` changes, regenerate the
artifact and restart the service. A stale artifact fails source-manifest
verification at startup.
