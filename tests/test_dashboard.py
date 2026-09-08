import json
import threading
from http.client import HTTPConnection

import pytest

import keyring.dashboard as dashboard_module
from keyring.dashboard import build_dashboard_state, create_server, load_dashboard_state


def test_dashboard_exposes_read_only_state(tmp_path) -> None:
    source = tmp_path / "evidence.jsonl"
    source.write_text("\n")
    server = create_server(source, host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        connection = HTTPConnection("127.0.0.1", port, timeout=2)
        connection.request("GET", "/api/state")
        response = connection.getresponse()
        payload = json.loads(response.read())
        assert response.status == 200
        assert payload["status"] == "DEGRADED"

        connection.request("POST", "/api/state")
        response = connection.getresponse()
        response.read()
        assert response.status == 405
        connection.close()
    finally:
        server.shutdown()
    thread.join(timeout=2)
    server.server_close()


def test_dashboard_state_artifact_is_deterministic_and_source_bound(tmp_path, monkeypatch):
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    (evidence / "records.jsonl").write_text("\n", encoding="utf-8")
    strategy = tmp_path / "strategy.yaml"
    strategy.write_text("capabilities: []\n", encoding="utf-8")
    output = tmp_path / "state.json"
    measured = {"status": "MEASURED", "records_replayed": 1}
    monkeypatch.setattr(dashboard_module, "dashboard_state", lambda *_: measured)

    first = build_dashboard_state(evidence, strategy, output)
    first_bytes = output.read_bytes()
    second = build_dashboard_state(evidence, strategy, output)

    assert first == second
    assert output.read_bytes() == first_bytes
    assert set(first["source_manifest"]) == {
        "evidence/records.jsonl",
        "strategy/strategy.yaml",
    }
    assert load_dashboard_state(output, evidence, strategy) == measured

    absolute_evidence = evidence.resolve()
    absolute_strategy = strategy.resolve()
    assert load_dashboard_state(output, absolute_evidence, absolute_strategy) == measured

    (evidence / "records.jsonl").write_text("changed\n", encoding="utf-8")
    with pytest.raises(ValueError, match="retained evidence"):
        load_dashboard_state(output, evidence, strategy)


def test_dashboard_state_artifact_rejects_degraded_evidence(tmp_path, monkeypatch):
    monkeypatch.setattr(
        dashboard_module,
        "dashboard_state",
        lambda *_: {"status": "DEGRADED", "reason": "bad chain"},
    )
    with pytest.raises(ValueError, match="refusing to write"):
        build_dashboard_state(tmp_path, tmp_path / "strategy.yaml", tmp_path / "state.json")
