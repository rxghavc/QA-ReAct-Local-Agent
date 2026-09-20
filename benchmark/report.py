"""Aggregates per-run JSON logs into a summary table.

Two things here follow directly from Milestone 7's findings, and both
change what the numbers mean:

- **Skipped tasks are excluded, not counted as failures.** A task whose
  site was unreachable was never measured (see benchmark/health.py), so it
  shrinks the denominator rather than depressing the rate.
- **A pass rate is reported with its spread, not as a single number.** The
  same seven tasks scored anywhere from 2/7 to 7/7 across six runs of
  identical code, so a bare average hides the only interesting part. Where
  a task has been attempted more than once, its own pass rate is shown.

One caveat this module cannot fix on its own: `logs/` accumulates across
milestones, so aggregating all of it blends runs made against different
code, different prompts and different task counts. Those are not
comparable, and averaging them produces a number that describes no
particular version of anything. So `--last N` scopes the report to the
most recent N task runs, and the time span covered is always printed, to
keep the reader aware of what is being averaged.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

from benchmark.failure_taxonomy import classify_failure

LOGS_DIR = Path(__file__).parent.parent / "logs"

EMPTY_REPORT: dict = {
    "logs": 0,
    "scored": 0,
    "skipped": 0,
    "span": None,
    "pass_rate": None,
    "self_report_accuracy": None,
    "avg_steps": None,
    "avg_model_seconds": None,
    "avg_tool_seconds": None,
    "tasks": [],
    "failures": [],
}


def build_report(logs_dir: Path | str = LOGS_DIR, last: int | None = None) -> dict:
    """Aggregate run logs. `last` keeps only the N most recently written.

    Ordering is by file modification time rather than by filename, because
    filenames sort by task id first: a glob-order "last N" would silently
    take N runs of whichever task sorts last, which is how an earlier
    verification script in this project ended up reading a stale log.
    """
    paths = sorted(Path(logs_dir).glob("*.json"), key=lambda p: p.stat().st_mtime)
    if last is not None:
        paths = paths[-last:]

    records = []
    for path in paths:
        try:
            record = json.loads(path.read_text())
        except json.JSONDecodeError:
            continue
        record["_mtime"] = path.stat().st_mtime
        records.append(record)

    if not records:
        return dict(EMPTY_REPORT)

    span = (
        min(r["_mtime"] for r in records),
        max(r["_mtime"] for r in records),
    )

    # Logs written before the skip field existed are scored runs by
    # definition, since skipping did not exist yet.
    scored = [r for r in records if r.get("skipped") is None]
    skipped = [r for r in records if r.get("skipped") is not None]

    by_task: dict[str, list[dict]] = defaultdict(list)
    for record in scored:
        by_task[record["task_id"]].append(record)

    # .get(..., 0) throughout: logs written before this timing breakdown
    # existed have neither field, and should average in as 0 rather than
    # break the report or silently drop from the denominator.
    tasks = []
    for task_id, attempts in sorted(by_task.items()):
        passes = sum(1 for r in attempts if r["passed"])
        tasks.append(
            {
                "task_id": task_id,
                "attempts": len(attempts),
                "passes": passes,
                "pass_rate": round(passes / len(attempts), 2),
                "avg_steps": round(
                    sum(r["steps"] for r in attempts) / len(attempts), 1
                ),
                "avg_wall_clock_seconds": round(
                    sum(r["wall_clock_seconds"] for r in attempts) / len(attempts), 1
                ),
                "avg_model_seconds": round(
                    sum(r.get("model_seconds_total", 0) for r in attempts)
                    / len(attempts),
                    1,
                ),
                "avg_tool_seconds": round(
                    sum(r.get("tool_seconds_total", 0) for r in attempts)
                    / len(attempts),
                    1,
                ),
            }
        )

    if not scored:
        report = dict(EMPTY_REPORT)
        report.update({"logs": len(records), "skipped": len(skipped), "span": span})
        return report

    passed = sum(1 for r in scored if r["passed"])
    # Negative-test tasks record None, because their success condition *is*
    # the agent's own report, which makes the metric circular. They are
    # excluded from the denominator rather than counted as wrong.
    judged = [r for r in scored if r.get("self_report_correct") is not None]
    correct = sum(1 for r in judged if r["self_report_correct"])

    failure_counts: dict[str, int] = defaultdict(int)
    for record in scored:
        if record["passed"] is False:
            failure_counts[classify_failure(record)] += 1
    failures = [
        {"category": category, "count": count}
        for category, count in sorted(
            failure_counts.items(), key=lambda item: item[1], reverse=True
        )
    ]

    return {
        "logs": len(records),
        "scored": len(scored),
        "skipped": len(skipped),
        "span": span,
        "pass_rate": round(passed / len(scored), 2),
        "self_report_accuracy": (round(correct / len(judged), 2) if judged else None),
        "avg_steps": round(sum(r["steps"] for r in scored) / len(scored), 1),
        "avg_model_seconds": round(
            sum(r.get("model_seconds_total", 0) for r in scored) / len(scored), 1
        ),
        "avg_tool_seconds": round(
            sum(r.get("tool_seconds_total", 0) for r in scored) / len(scored), 1
        ),
        "tasks": tasks,
        "failures": failures,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Summarise benchmark run logs.")
    parser.add_argument(
        "--last",
        type=int,
        metavar="N",
        help=(
            "only aggregate the N most recent task runs. logs/ accumulates "
            "across milestones, and runs made against different code are not "
            "comparable, so an all-time average describes no particular "
            "version. For one full pass of the current suite, N is the task "
            "count; for three passes, three times it"
        ),
    )
    args = parser.parse_args()

    report = build_report(last=args.last)
    if report["logs"] == 0:
        print("No run logs found in logs/. Run benchmark/runner.py first.")
    elif report["scored"] == 0:
        print(
            f"{report['logs']} logs found but none were scored "
            f"({report['skipped']} skipped for unreachable sites). No result."
        )
    else:
        first, last_seen = report["span"]
        print(
            f"Task runs scored: {report['scored']}"
            + (f" (of the {args.last} most recent)" if args.last else " (all logs)")
        )
        print(
            "Covering: "
            + datetime.fromtimestamp(first, UTC).strftime("%Y-%m-%d %H:%M")
            + " to "
            + datetime.fromtimestamp(last_seen, UTC).strftime("%Y-%m-%d %H:%M")
            + " UTC"
        )
        if report["skipped"]:
            print(f"Skipped (site unreachable, not counted): {report['skipped']}")
        print(f"Pass rate: {report['pass_rate']:.0%}")
        if report["self_report_accuracy"] is None:
            print("Self-report accuracy: n/a (no task where it is measurable)")
        else:
            print(f"Self-report accuracy: {report['self_report_accuracy']:.0%}")
        print(f"Average steps per task run: {report['avg_steps']}")
        print(
            f"Average time per task run: {report['avg_model_seconds']}s model "
            f"inference, {report['avg_tool_seconds']}s tool execution"
        )
        print()
        for task in report["tasks"]:
            print(
                f"  {task['task_id']}: {task['passes']}/{task['attempts']} "
                f"({task['pass_rate']:.0%}), avg {task['avg_steps']} steps, "
                f"avg {task['avg_wall_clock_seconds']}s "
                f"({task['avg_model_seconds']}s model, "
                f"{task['avg_tool_seconds']}s tool)"
            )
        repeated = [t for t in report["tasks"] if t["attempts"] > 1]
        if repeated and any(0 < t["pass_rate"] < 1 for t in repeated):
            print(
                "\nSome tasks pass only sometimes. That variance is a real "
                "property of the agent,\nnot noise to average away: a single "
                "run of this suite does not support a conclusion."
            )
        if report["failures"]:
            print("\nFailure taxonomy (fix the largest bucket first):")
            for failure in report["failures"]:
                print(f"  {failure['category']}: {failure['count']}")
