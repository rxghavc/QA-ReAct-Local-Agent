"""A small, committed log of regression-gate measurements over time.

The plan's own "Regression tracking" item asked for this explicitly:
"re-run the full suite on every meaningful code change and log the
pass-rate trend over time... turns the benchmark into a lightweight CI
for the agent itself." `benchmark/regression_gate.py` (Milestone 10
part 4) already answers "did this specific change regress anything," a
point-in-time yes/no; this answers a different question, "how has the
suite actually moved over time," which needs a durable history, not a
fresh computation from `logs/` (gitignored, and pruned/rotated locally,
so it can't be the source of a trend that outlives one machine).

`benchmark/trend.jsonl` is committed: one small line per real gate run,
unlike the bulky per-task traces in `logs/`. `regression_gate.py`
appends to it by default every time it runs, since a gate run already
is the "meaningful code change" checkpoint the plan asked to log
against; that script's `--no-record` opts a specific run out (matching
the `--no-routing`/`--history-trim` opt-out pattern already used
elsewhere), for exploratory measurement that shouldn't pollute the
permanent record.
"""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

HISTORY_PATH = Path(__file__).parent / "trend.jsonl"


def _git_commit() -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def append_entry(
    pass_rates: list[float],
    gate_threshold: float,
    gate_passed: bool,
    path: Path | str = HISTORY_PATH,
) -> dict:
    """Records one gate run. `pass_rates` is kept per-pass, not
    pre-averaged, so a future reader can see the spread this project
    insists matters (see `benchmark/runner.py`'s own docstring), not
    just a single collapsed number.
    """
    entry = {
        "measured_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "commit": _git_commit(),
        "num_runs": len(pass_rates),
        "pass_rates": [round(r, 4) for r in pass_rates],
        "min_pass_rate": round(min(pass_rates), 4),
        "mean_pass_rate": round(sum(pass_rates) / len(pass_rates), 4),
        "max_pass_rate": round(max(pass_rates), 4),
        "gate_threshold": round(gate_threshold, 4),
        "gate_passed": gate_passed,
    }
    path = Path(path)
    with path.open("a") as f:
        f.write(json.dumps(entry) + "\n")
    return entry


def load_entries(path: Path | str = HISTORY_PATH) -> list[dict]:
    path = Path(path)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def format_trend(entries: list[dict]) -> str:
    if not entries:
        return (
            "No trend history recorded yet. Run benchmark/regression_gate.py "
            "to add the first entry."
        )
    header = (
        f"{'measured_at':<21} {'commit':<9} {'runs':>4}  "
        f"{'min':>5}  {'mean':>5}  {'max':>5}  gate"
    )
    lines = [header]
    for e in entries:
        commit = e.get("commit") or "?"
        lines.append(
            f"{e['measured_at']:<21} {commit:<9} {e['num_runs']:>4}  "
            f"{e['min_pass_rate']:>4.0%}  {e['mean_pass_rate']:>4.0%}  "
            f"{e['max_pass_rate']:>4.0%}  "
            f"{'PASS' if e['gate_passed'] else 'FAIL'} "
            f"(threshold {e['gate_threshold']:.0%})"
        )
    return "\n".join(lines)


if __name__ == "__main__":
    print(format_trend(load_entries()))
