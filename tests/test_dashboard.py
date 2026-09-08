import json
import threading
from http.client import HTTPConnection

import pytest

from keyring.dashboard import create_server


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


def test_dashboard_rejects_invalid_static_state_before_starting(tmp_path) -> None:
    source = tmp_path / "evidence.jsonl"
    source.write_text("\n")
    state = tmp_path / "state.json"
    state.write_text(json.dumps(["not", "an", "object"]))
    with pytest.raises(ValueError, match="JSON object"):
        create_server(source, host="127.0.0.1", port=0, state_file=state)
