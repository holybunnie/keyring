from __future__ import annotations

import pytest

from keyring.config import load_strategy_config
from keyring.leastprivilege import diff, needed_capabilities, render


@pytest.fixture(scope="module")
def result():
    return diff()


def test_manifest_flags_map_to_capabilities():
    strategy = load_strategy_config().model
    needed = needed_capabilities(strategy)
    # The example manifest declares spot symbols and sets margin/futures/transfer false.
    assert "spot" in needed
    assert "margin" not in needed
    assert "transfer" not in needed
    # `futures: false` must decline BOTH futures products, not just one.
    assert "usd_m_futures" not in needed
    assert "coin_m_futures" not in needed


def test_futures_flag_enables_both_futures_capabilities():
    strategy = load_strategy_config().model
    strategy.needs.futures = True
    needed = needed_capabilities(strategy)
    assert {"usd_m_futures", "coin_m_futures"} <= needed


def test_measured_excess_is_a_subset_of_verified(result):
    """Excess may only be claimed for capabilities actually proved to work."""
    assert set(result["measured_excess_capabilities"]) <= set(result["verified_capabilities"])


def test_measured_excess_excludes_everything_the_manifest_needs(result):
    assert not set(result["measured_excess_capabilities"]) & set(result["needed_capabilities"])


def test_potential_and_measured_excess_are_never_merged(result):
    """Part IX: a listed instrument count is not effective authority."""
    instruments = result["instruments"]
    assert instruments["status"] in {"POTENTIAL_SURFACE_ONLY", "UNAVAILABLE"}
    if instruments["status"] == "POTENTIAL_SURFACE_ONLY":
        assert "NOT measured reach" in instruments["label"]
        # The two counts must remain separately addressable.
        assert "potential_excess_count" in instruments
        assert "measured_excess_write_tool_count" in result
        assert instruments["potential_excess_count"] != result["measured_excess_write_tool_count"]


def test_potential_excess_is_listed_minus_required(result):
    instruments = result["instruments"]
    if instruments["status"] != "POTENTIAL_SURFACE_ONLY":
        pytest.skip("no instrument inventory in the evidence log")
    listed = instruments["listed_trading_instruments"]
    required = instruments["required_by_strategy"]
    # Required symbols may or may not all be listed as trading, so the excess can
    # never exceed the listed count and can never be negative.
    assert 0 <= instruments["potential_excess_count"] <= listed
    assert instruments["potential_excess_count"] >= listed - required


def test_remediation_cost_comes_from_evidence(result):
    remediation = result["remediation"]
    assert remediation["label"] in {"OBSERVED", "INCONCLUSIVE"}
    if remediation["label"] == "OBSERVED":
        assert remediation["outcome"] in {"RECONNECT_REQUIRED", "UPDATED_IN_PLACE"}
        assert remediation["source"]


def test_unmet_needs_are_reported(result):
    """A needed capability that is not VERIFIED must surface, not be silently dropped."""
    assert set(result["unmet_needs"]) == set(result["needed_capabilities"]) - set(
        result["verified_capabilities"]
    )


def test_render_never_prints_a_merged_total(result):
    text = render(result)
    assert "EXCESS — MEASURED" in text
    assert "EXCESS — POTENTIAL" in text
    # A single combined "excess" headline number would violate Part IX.
    assert "TOTAL EXCESS" not in text.upper()


def test_strategy_config_is_checksummed(result):
    assert len(result["strategy_config_sha256"]) == 64
