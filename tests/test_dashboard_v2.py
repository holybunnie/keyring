from __future__ import annotations

import json
import threading
from http.client import HTTPConnection

import pytest

from keyring.dashboard import create_server, dashboard_state, render_html


@pytest.fixture(scope="module")
def state():
    return dashboard_state("evidence/raw")


def test_status_is_measured_only_when_something_was_verified(state):
    verified = [
        name for name, row in state["authority"].items() if row["classification"] == "VERIFIED"
    ]
    assert (state["status"] == "MEASURED") == bool(verified)


def test_budget_and_rate_limit_are_always_present(state):
    """Part VII: these are permanently visible, not on a sub-page."""
    safety = state["safety"]
    assert "probe_budget" in safety
    assert safety["rate_limit_status"]
    assert safety["last_429"]
    assert safety["probes_used"] <= (safety["max_probes_per_run"] or safety["probes_used"])


def test_budget_is_rendered_in_the_page(state):
    page = render_html(state)
    assert state["safety"]["probe_budget"] in page
    assert state["safety"]["rate_limit_status"] in page


def test_every_capability_row_has_a_proof_chain(state):
    """Law 6: no badge without the evidence that produced it."""
    for name, row in state["authority"].items():
        chain = state["traces"].get(name, {}).get("steps", [])
        assert chain, f"{name} has no proof chain"
        for step in chain:
            assert step["label"] in {"OBSERVED", "DOCUMENTED", "ASSUMED", "INCONCLUSIVE"}


def test_probed_capabilities_cite_an_evidence_record(state):
    for name, row in state["authority"].items():
        if row["classification"] != "VERIFIED":
            continue
        steps = state["traces"][name]["steps"]
        probe = [s for s in steps if s["step"] == "probe"]
        assert probe and "#" in probe[0]["evidence"], f"{name} probe cites no record"


def test_contradictions_are_all_labelled(state):
    for row in state["contradictions"]:
        assert row["label"]
        assert row["measured"]


def test_revocation_is_visible_and_honest_without_a_trial(state):
    revocation = state["revocation"]
    assert revocation["status"] == "INCONCLUSIVE"
    assert revocation["n"] == 0
    assert revocation["convergence_seconds"] is None
    page = render_html(state)
    assert "Revocation observation" in page
    assert revocation["reason"] in page


def test_degraded_when_evidence_is_empty(tmp_path):
    (tmp_path / "evidence.jsonl").write_text("\n")
    state = dashboard_state(tmp_path)
    assert state["status"] == "DEGRADED"
    assert "reason" in state
    # A degraded page must not present measured effective authority.
    assert "least_privilege" not in state
    assert "financial_reach" not in state


def _serve(path):
    server = create_server(path, host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def test_server_is_read_only(tmp_path):
    (tmp_path / "evidence.jsonl").write_text("\n")
    server, thread = _serve(tmp_path)
    try:
        port = server.server_address[1]
        for method in ("POST", "PUT", "DELETE", "PATCH"):
            connection = HTTPConnection("127.0.0.1", port, timeout=5)
            connection.request(method, "/api/state")
            response = connection.getresponse()
            response.read()
            assert response.status == 405, method
            connection.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_api_state_serves_json(tmp_path):
    (tmp_path / "evidence.jsonl").write_text("\n")
    server, thread = _serve(tmp_path)
    try:
        port = server.server_address[1]
        connection = HTTPConnection("127.0.0.1", port, timeout=5)
        connection.request("GET", "/api/state")
        response = connection.getresponse()
        payload = json.loads(response.read())
        assert response.status == 200
        assert payload["status"] == "DEGRADED"
        connection.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
