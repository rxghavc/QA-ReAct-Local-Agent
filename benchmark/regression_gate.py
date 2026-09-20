"""A regression gate: fails when the suite has really regressed, not when
it's merely noisy.

docs/ai-infra-and-observability.md's fourth observability item wanted a
gate "sized to the measured noise band, not a guessed threshold." This
project has that measurement: three `--repeat 3` passes after the
report_done/report_blocked and ask_clarification fixes (PR #13) scored
58%, 75%, 92% min/mean/max (see benchmark/baseline.json and README's
Agent runtime metrics), a spread already established as a real property
of this agent, not noise to average away (Milestone 7).

A threshold set *at* the observed floor (58%) would still flap: a
perfectly healthy run reproducing that same floor is, by definition, not
a regression, and this suite has already shown it can happen with no
code change at all. So `gate_threshold` sets the line *below* the
observed floor instead, rounded to a clean 5-percentage-point step, so
routine variance clears it and a genuine regression (the suite doing
meaningfully worse than its worst honest run, not just an unlucky one)
is what actually trips it.

Deliberately not wired into .github/workflows/ci.yml: every other CI job
(lint, typecheck, test, security, docker-build) runs against static code
with no live model or browser, exactly why they can run on a GitHub-hosted
runner at all. This suite needs a local qwen2.5-coder:14b via Ollama and
a real browser session against live sites, the same reason
`benchmark/runner.py` and `report.py` are already documented as local,
manual commands in docs/how-to-run.md rather than CI steps. This is a
tool for that same local workflow: run it after a change you expect
might move the pass rate, before merging.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from benchmark.runner import per_run_pass_rates, run_suite_repeated

BASELINE_PATH = Path(__file__).parent / "baseline.json"
MIN_REPEAT_FOR_GATE = 2


def load_baseline(path: Path | str = BASELINE_PATH) -> dict:
    return json.loads(Path(path).read_text())


def gate_threshold(baseline: dict) -> float:
    """The pass rate a fresh measurement's mean must clear, strictly
    below `baseline["min_pass_rate"]` and rounded down to a clean 5-point
    step, so it never coincides with the observed floor itself. 58% ->
    55%, 60% -> 55%, 83% -> 80%: always at least one point of headroom
    below the floor, even when the floor already lands on a 5-point line.
    """
    floor_percent = round(baseline["min_pass_rate"] * 100)
    threshold_percent = ((floor_percent - 1) // 5) * 5
    return threshold_percent / 100


def check_regression(pass_rates: list[float], baseline: dict) -> tuple[bool, str]:
    """Compares the *mean* of a fresh multi-pass measurement against the
    gate threshold, not any single pass's rate. A single low pass among
    several is exactly the noise this suite is documented to produce; the
    mean is the same statistic the baseline itself was built from.
    """
    threshold = gate_threshold(baseline)
    mean_rate = sum(pass_rates) / len(pass_rates)
    ok = mean_rate >= threshold
    message = (
        f"mean pass rate {mean_rate:.0%} over {len(pass_rates)} run(s) "
        f"({', '.join(f'{r:.0%}' for r in pass_rates)}) vs. gate threshold "
        f"{threshold:.0%} (baseline: min {baseline['min_pass_rate']:.0%}, "
        f"mean {baseline['mean_pass_rate']:.0%}, max {baseline['max_pass_rate']:.0%} "
        f"over {baseline['num_runs']} runs, measured {baseline['measured_at']})"
    )
    return ok, message


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repeat",
        type=int,
        default=3,
        metavar="N",
        help=(
            "suite passes to run before checking the gate (default 3, "
            f"minimum {MIN_REPEAT_FOR_GATE}). A single pass cannot support "
            "a regression check on a suite with this much run-to-run "
            "variance, so fewer than the minimum is rejected outright "
            "rather than silently gating on noise"
        ),
    )
    parser.add_argument(
        "--no-routing",
        action="store_true",
        help="disable the same-failure routing checkpoint (see benchmark/runner.py)",
    )
    args = parser.parse_args()
    if args.repeat < MIN_REPEAT_FOR_GATE:
        parser.error(f"--repeat must be at least {MIN_REPEAT_FOR_GATE}")

    baseline = load_baseline()
    runs = run_suite_repeated(use_routing=not args.no_routing, repeat=args.repeat)
    pass_rates = per_run_pass_rates(runs)

    if not pass_rates:
        print("GATE: NO RESULT, every pass had every task skipped")
        sys.exit(1)

    ok, message = check_regression(pass_rates, baseline)
    print(("GATE PASS: " if ok else "GATE FAIL: ") + message)
    sys.exit(0 if ok else 1)
