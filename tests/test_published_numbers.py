"""Every number published in the README must match the evidence log.

This exists because hand-typed figures drifted from the log more than once
during the build. A published number that nothing recomputes is exactly the
kind of unverified claim this project says is a defect, so the check is a test
rather than a habit.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from keyring.authority import derive
from keyring.leastprivilege import diff

README = Path("README.md")


@pytest.fixture(scope="module")
def published():
    return README.read_text()


@pytest.fixture(scope="module")
def measured():
    return derive()


def _one(pattern: str, text: str) -> int:
    match = re.search(pattern, text)
    assert match, f"README no longer contains a figure matching {pattern!r}"
    return int(match.group(1).replace(",", ""))


def test_records_replayed_matches(published, measured):
    assert _one(r"records replayed\s+(\d+)", published) == measured["records_replayed"]


def test_state_digest_count_matches(published, measured):
    assert _one(r"state digests seen\s+(\d+)", published) == measured["state_digests_seen"]


def test_distinct_state_count_matches(published, measured):
    assert _one(r"distinct states\s+(\d+)", published) == measured["distinct_states"]


def test_readme_claims_a_single_state_only_if_true(published, measured):
    """The zero-state-change headline may only stand while the evidence supports it."""
    claims_identical = "identical throughout   True" in published
    assert claims_identical == measured["state_identical_throughout"]


def test_listed_instrument_count_matches(published):
    result = diff()
    if result["instruments"]["status"] != "POTENTIAL_SURFACE_ONLY":
        pytest.skip("no instrument inventory in the evidence log")
    assert _one(r"venue lists ([\d,]+) spot", published) == result["instruments"][
        "listed_trading_instruments"
    ]


def test_granted_scope_matches(published, measured):
    assert measured["granted_scope"] in published


def test_every_verified_capability_is_named_in_the_readme(published, measured):
    """A capability proved to work must not be quietly absent from the writeup."""
    for name, row in measured["capabilities"].items():
        if row["classification"] == "VERIFIED" and row["probe_tool"]:
            assert row["probe_tool"] in published, f"{row['probe_tool']} missing from README"


LABELS = ("**OBSERVED", "**DOCUMENTED", "**ASSUMED", "**INCONCLUSIVE")


def test_no_unlabelled_numeric_claims(published):
    """Law 1, aimed at what actually drifts: a published figure carries a label.

    Instructions and headings are not claims. A sentence asserting a number is,
    and every hand-typed number in this build drifted from the log at least once.
    """
    body = published.split("## Results", 1)[1].split("## Limits", 1)[0]
    offenders = []
    in_fence = False
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            # Fenced blocks are generated command output, not prose claims.
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if not stripped or stripped.startswith(("|", "#", ">", "-")):
            continue
        if stripped.startswith(LABELS):
            continue
        # Filenames and identifiers are not claims: `docs/m0.md` and
        # `spot.newOrder` carry digits without asserting a measurement.
        prose = re.sub(r"\[[^\]]*\]\([^)]*\)", "", stripped)
        prose = re.sub(r"`[^`]*`", "", prose)
        # A prose line asserting a figure must be labelled.
        if re.search(r"\d", prose) and re.search(r"[a-z]{4,}", prose):
            offenders.append(stripped[:100])
    assert not offenders, f"unlabelled numeric claims in results: {offenders}"
