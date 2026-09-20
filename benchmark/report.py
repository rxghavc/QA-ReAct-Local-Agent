"""Aggregates per-run JSON logs into a summary table."""

from __future__ import annotations

import json
from pathlib import Path

LOGS_DIR = Path(__file__).parent.parent / "logs"


def build_report(logs_dir: Path | str = LOGS_DIR) -> dict:
    records = [
        json.loads(path.read_text()) for path in sorted(Path(logs_dir).glob("*.json"))
    ]

    if not records:
        return {
            "runs": 0,
            "pass_rate": None,
            "self_report_accuracy": None,
            "avg_steps": None,
            "tasks": [],
        }

    passed = sum(1 for r in records if r["passed"])
    self_report_correct = sum(1 for r in records if r["self_report_correct"])

    return {
        "runs": len(records),
        "pass_rate": round(passed / len(records), 2),
        "self_report_accuracy": round(self_report_correct / len(records), 2),
        "avg_steps": round(sum(r["steps"] for r in records) / len(records), 1),
        "tasks": [
            {
                "task_id": r["task_id"],
                "passed": r["passed"],
                "self_report": r["self_report"],
                "steps": r["steps"],
                "wall_clock_seconds": r["wall_clock_seconds"],
            }
            for r in records
        ],
    }


if __name__ == "__main__":
    report = build_report()
    if report["runs"] == 0:
        print("No run logs found in logs/. Run benchmark/runner.py first.")
    else:
        print(f"Runs logged: {report['runs']}")
        print(f"Pass rate: {report['pass_rate']:.0%}")
        print(f"Self-report accuracy: {report['self_report_accuracy']:.0%}")
        print(f"Average steps per task: {report['avg_steps']}")
        print()
        for task in report["tasks"]:
            marker = "PASS" if task["passed"] else "FAIL"
            print(
                f"  [{marker}] {task['task_id']} "
                f"(self-report: {task['self_report']}, steps: {task['steps']}, "
                f"{task['wall_clock_seconds']}s)"
            )
