from __future__ import annotations

import json

import pytest

from keyring.session import SessionUnavailable, from_codex_credentials


def test_codex_credentials_loader_reads_scope_without_logging_token(tmp_path):
    path = tmp_path / "credentials.json"
    path.write_text(
        json.dumps(
            {
                "binance|entry": {
                    "access_token": "secret-access-token",
                    "server_url": "https://agent.example/mcp",
                    "server_name": "binance",
                    "scopes": ["mcp:account:read", "mcp:spot:trade"],
                    "expires_at": 4102444800000,
                    "client_id": "codex-client",
                }
            }
        )
    )

    session = from_codex_credentials(path)

    assert session.authorization == "Bearer secret-access-token"
    assert session.granted_scope == "mcp:account:read mcp:spot:trade"
    assert session.metadata()["granted_scope"] == "mcp:account:read mcp:spot:trade"
    assert "secret-access-token" not in repr(session.metadata())


def test_codex_credentials_loader_refuses_ambiguous_binance_sessions(tmp_path):
    path = tmp_path / "credentials.json"
    path.write_text(
        json.dumps(
            {
                "binance|first": {"access_token": "one"},
                "binance|second": {"access_token": "two"},
            }
        )
    )

    with pytest.raises(SessionUnavailable, match="refusing to guess"):
        from_codex_credentials(path)
