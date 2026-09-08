from __future__ import annotations

from keyring.trace import trace


def test_every_current_trace_step_resolves_to_evidence() -> None:
    result = trace("evidence/raw")
    for capability, entry in result["capabilities"].items():
        assert entry["steps"], capability
        for step in entry["steps"]:
            assert step["evidence_records"], (capability, step["step"])
            assert all("#" in reference for reference in step["evidence_records"])


def test_current_probe_trace_exposes_plan_and_final_classification() -> None:
    result = trace("evidence/raw")
    spot_steps = {step["step"]: step for step in result["capabilities"]["spot"]["steps"]}
    assert "probe plan" in spot_steps
    assert "planned_by model" in spot_steps["probe plan"]["value"]
    assert "final classification VERIFIED" in spot_steps["probe"]["value"]
    assert "recorded outcome INCONCLUSIVE" not in spot_steps["probe"]["value"]
    assert spot_steps["classification"]["value"] == "VERIFIED"
