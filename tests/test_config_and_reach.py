from pathlib import Path

from keyring.config import load_probe_config, load_strategy_config
from keyring.labels import Classification
from keyring.models import ClassificationResult
from keyring.reach import least_privilege_diff


ROOT = Path(__file__).parents[1]


def test_config_load_is_checksummed() -> None:
    probes = load_probe_config(ROOT / "config/probes.yaml")
    strategy = load_strategy_config(ROOT / "config/strategy.yaml")
    assert len(probes.sha256) == 64
    assert len(strategy.sha256) == 64
    assert probes.model.budgets.max_probes_per_run == 7


def test_strategy_diff_does_not_call_potential_symbols_effective() -> None:
    strategy = load_strategy_config(ROOT / "config/strategy.yaml").model
    results = [
        ClassificationResult(
            capability="spot",
            classification=Classification.INCONCLUSIVE,
            reason="no live session",
        )
    ]
    diff = least_privilege_diff(strategy, results, potential_spot_symbols=["BTCUSDT", "ETHUSDT", "SOLUSDT"])
    assert diff["spot_symbol_status"] == "POTENTIAL_SURFACE_ONLY"
    assert diff["spot_symbol_label"] == "DOCUMENTED"
    assert diff["excess_spot_symbol_count"] == 1
    assert diff["verified_capabilities"] == []
