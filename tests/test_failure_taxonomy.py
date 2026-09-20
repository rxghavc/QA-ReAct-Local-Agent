"""Tests for benchmark/failure_taxonomy.py, run against real captured
failed runs (tests/fixtures/failure_taxonomy/), not hand-written
fixtures. Milestone 7's lesson was exactly this: a rule validated on
tidy hand-written inputs passed its tests and then got every real
activation wrong, because real failures don't look like tidy examples.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmark.failure_taxonomy import FAILURE_CATEGORIES, classify_failure

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "failure_taxonomy"


def _load(name: str) -> dict:
    return json.loads((FIXTURES_DIR / f"{name}.json").read_text())


@pytest.mark.parametrize(
    "fixture,expected",
    [
        ("unparseable_model_output", "unparseable_model_output"),
        ("environment_flakiness_application_error", "environment_flakiness"),
        ("environment_flakiness_network_error", "environment_flakiness"),
        ("tool_semantics_mismatch", "tool_semantics_mismatch"),
        ("ambiguity_not_recognized", "ambiguity_not_recognized"),
        ("invalid_selector_syntax", "invalid_selector_syntax"),
        ("selector_drift", "selector_drift"),
        ("hallucinated_success", "hallucinated_success"),
        ("unclassified_inert_click", "unclassified"),
    ],
)
def test_classify_failure_on_real_captured_runs(fixture, expected):
    assert classify_failure(_load(fixture)) == expected


def test_every_category_has_at_least_one_real_fixture():
    """A category with no real example backing it is a guess, not a
    finding; docs/milestones/failure-taxonomy.md explains why "premature
    give-up" and "context overflow" from the plan's own suggested list
    are deliberately absent rather than invented."""
    exercised = {classify_failure(_load(p.stem)) for p in FIXTURES_DIR.glob("*.json")}
    assert exercised == set(FAILURE_CATEGORIES)


def test_ambiguity_not_recognized_takes_priority_over_selector_drift():
    """task_12's real failures usually have a genuine selector-timeout
    error (hunting for the "Add to basket" button) *and* are a
    negative-tier task. The negative-tier signal must win: which
    selector failed this particular run is far less informative than
    "still never asks for clarification," which is the actual defect
    this task exists to catch."""
    record = _load("ambiguity_not_recognized")
    assert record["self_report_correct"] is None
    assert any(
        step.get("result", {}).get("success") is False for step in record["trace"]
    )
    assert classify_failure(record) == "ambiguity_not_recognized"
