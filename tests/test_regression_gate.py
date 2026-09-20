"""Unit tests for benchmark/regression_gate.py."""

from benchmark.regression_gate import check_regression, gate_threshold, load_baseline

BASELINE = {
    "measured_at": "2026-09-18",
    "num_runs": 3,
    "min_pass_rate": 0.58,
    "max_pass_rate": 0.92,
    "mean_pass_rate": 0.75,
    "source": "test fixture",
}


def test_gate_threshold_sits_below_the_observed_floor():
    assert gate_threshold(BASELINE) == 0.55


def test_gate_threshold_stays_below_the_floor_even_on_a_clean_five_point_line():
    """58% is not itself a multiple of 5, so the naive "round down to the
    nearest 5" could coincide with the floor on a baseline that already
    is one (60%, 80%, ...). The threshold must still land strictly below
    it, not equal to it, or a baseline re-measurement landing on a clean
    number would silently stop giving any headroom at all."""
    assert gate_threshold({**BASELINE, "min_pass_rate": 0.60}) == 0.55
    assert gate_threshold({**BASELINE, "min_pass_rate": 0.80}) == 0.75


def test_check_regression_passes_when_the_mean_clears_the_threshold():
    ok, message = check_regression([0.58, 0.75, 0.92], BASELINE)
    assert ok is True
    assert "75%" in message
    assert "55%" in message


def test_check_regression_passes_on_a_single_noise_floor_run():
    """The suite has genuinely reproduced 58% with no code change
    (Milestone 7). A gate that fails on that exact, already-seen number
    would flap on noise alone, which is the failure mode the plan's own
    ai-infra doc named explicitly."""
    ok, _ = check_regression([0.58], BASELINE)
    assert ok is True


def test_check_regression_fails_on_a_real_drop():
    ok, message = check_regression([0.33, 0.25, 0.42], BASELINE)
    assert ok is False
    assert "33%" in message


def test_check_regression_uses_the_mean_not_a_single_bad_pass():
    """One noisy pass among several must not sink the gate on its own;
    that's exactly the kind of single-run conclusion this project's own
    --repeat flag exists to avoid (see benchmark/runner.py)."""
    ok, _ = check_regression([0.92, 0.92, 0.30], BASELINE)
    assert ok is True


def test_load_baseline_reads_the_committed_file():
    baseline = load_baseline()
    assert 0.0 < baseline["min_pass_rate"] <= baseline["mean_pass_rate"]
    assert baseline["mean_pass_rate"] <= baseline["max_pass_rate"] <= 1.0
    assert baseline["num_runs"] >= 2
