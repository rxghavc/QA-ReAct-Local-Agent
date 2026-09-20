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
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

LOGS_DIR = Path(__file__).parent.parent / "logs"

EMPTY_REPORT: dict = {
    "logs": 0,
    "scored": 0,
    "skipped": 0,
    "pass_rate": None,
    "self_report_accuracy": None,
    "avg_steps": None,
    "tasks": [],
}


def build_report(logs_dir: Path | str = LOGS_DIR) -> dict:
    records = []
    for path in sorted(Path(logs_dir).glob("*.json")):
        try:
            records.append(json.loads(path.read_text()))
        except json.JSONDecodeError:
            continue

    if not records:
        return dict(EMPTY_REPORT)

    # Logs written before the skip field existed are scored runs by
    # definition, since skipping did not exist yet.
    scored = [r for r in records if r.get("skipped") is None]
    skipped = [r for r in records if r.get("skipped") is not None]

    by_task: dict[str, list[dict]] = defaultdict(list)
    for record in scored:
        by_task[record["task_id"]].append(record)

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
            }
        )

    if not scored:
        report = dict(EMPTY_REPORT)
        report.update({"logs": len(records), "skipped": len(skipped)})
        return report

    passed = sum(1 for r in scored if r["passed"])
    correct = sum(1 for r in scored if r["self_report_correct"])
    return {
        "logs": len(records),
        "scored": len(scored),
        "skipped": len(skipped),
        "pass_rate": round(passed / len(scored), 2),
        "self_report_accuracy": round(correct / len(scored), 2),
        "avg_steps": round(sum(r["steps"] for r in scored) / len(scored), 1),
        "tasks": tasks,
    }


if __name__ == "__main__":
    report = build_report()
    if report["logs"] == 0:
        print("No run logs found in logs/. Run benchmark/runner.py first.")
    elif report["scored"] == 0:
        print(
            f"{report['logs']} logs found but none were scored "
            f"({report['skipped']} skipped for unreachable sites). No result."
        )
    else:
        print(f"Task runs scored: {report['scored']}")
        if report["skipped"]:
            print(f"Skipped (site unreachable, not counted): {report['skipped']}")
        print(f"Pass rate: {report['pass_rate']:.0%}")
        print(f"Self-report accuracy: {report['self_report_accuracy']:.0%}")
        print(f"Average steps per task run: {report['avg_steps']}")
        repeated = [t for t in report["tasks"] if t["attempts"] > 1]
        print()
        for task in report["tasks"]:
            print(
                f"  {task['task_id']}: {task['passes']}/{task['attempts']} "
                f"({task['pass_rate']:.0%}), avg {task['avg_steps']} steps, "
                f"avg {task['avg_wall_clock_seconds']}s"
            )
        if repeated and any(0 < t["pass_rate"] < 1 for t in repeated):
            print(
                "\nSome tasks pass only sometimes. That variance is a real "
                "property of the agent,\nnot noise to average away: a single "
                "run of this suite does not support a conclusion."
            )
