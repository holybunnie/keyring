from __future__ import annotations

from pathlib import Path

from keyring.agent_replay import render, replay


EVIDENCE = Path("evidence/raw/0012-codex-cli-second-account.jsonl")


def test_default_replay_exposes_recorded_model_disagreement_without_mutation() -> None:
    before = EVIDENCE.stat()
    result = replay()
    after = EVIDENCE.stat()

    assert result["mode"] == "RECORDED_REPLAY"
    assert result["network_calls"] == 0
    assert result["evidence_mutated"] is False
    assert result["evidence_chains_verified"] is True
    assert result["runtime_schema"]["source"].endswith("#47")
    assert result["live_filters"]["source"].endswith("#12")
    assert result["live_filters"]["filter"]["minQty"] == "0.00001000"
    assert result["model_proposal"]["source"].endswith("#78")
    assert result["deterministic_gate"]["result"] == "ACCEPTED AS NON-EXECUTING TEST"
    assert result["controlled_request"]["positive_control_source"].endswith("#49")
    assert result["model_interpretation"]["classification"] == "VERIFIED"
    assert result["deterministic_result"]["classification"] == "INCONCLUSIVE"
    assert result["deterministic_result"]["disagreement"] is True
    assert result["account_state"]["unchanged"] is True
    assert result["account_state"]["complete"] is True
    assert (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns)


def test_replay_renderer_is_explicit_about_provenance_and_authority() -> None:
    output = render(replay())

    assert "KEYRING AGENT — RECORDED RUN" in output
    assert "no network · no reconnect · no mutation" in output
    assert "recomputed from retained schema + filters + proposal" in output
    assert "0012-codex-cli-second-account.jsonl#78" in output
    assert "Recorded model interpretation\n   VERIFIED" in output
    assert "Deterministic result\n   INCONCLUSIVE" in output
    assert output.endswith("The deterministic result wins.")
