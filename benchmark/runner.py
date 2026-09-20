"""Loads YAML task definitions, runs the agent against each, scores, and logs."""

from __future__ import annotations

import argparse
import json
import time
from datetime import UTC, datetime
from pathlib import Path

import yaml

from agent.loop import run_task
from agent.tools import execute_tool
from benchmark.health import task_skip_reason

TASKS_DIR = Path(__file__).parent / "tasks"
LOGS_DIR = Path(__file__).parent.parent / "logs"
DEFAULT_MAX_STEPS = 15


def load_tasks(tasks_dir: Path | str = TASKS_DIR) -> list[dict]:
    tasks: list[dict] = []
    for path in sorted(Path(tasks_dir).glob("*.yaml")):
        tasks.extend(yaml.safe_load(path.read_text()) or [])
    return tasks


def score_task(task: dict, final_browser_state: dict) -> bool:
    """Programmatic pass/fail, independent of the agent's own report_done/report_blocked claim.

    `final_browser_state` is whatever _fetch_final_state gathered after the
    loop ended: always the page's url/title/headings, plus `extracted_text`
    when the task's check needs it. Kept as a plain dict-in, bool-out
    function (no browser calls of its own) so it's trivial to unit test.
    """
    check = task["success_check"]
    check_type = check["type"]

    if check_type == "url_contains":
        return check["expected"] in final_browser_state.get("url", "")
    if check_type == "url_equals":
        return final_browser_state.get("url", "") == check["expected"]
    if check_type == "dom_text_contains":
        text = final_browser_state.get("extracted_text") or ""
        return check["expected"] in text

    raise ValueError(f"unknown success_check type: {check_type!r}")


def _fetch_final_state(success_check: dict) -> dict:
    """Query the browser for whatever score_task will need, right after the
    loop ends. The browser session is the same persistent page the agent
    just finished acting on, so this reads exactly the state the agent left
    behind, not a fresh page.
    """
    state = execute_tool({"name": "get_page_state", "arguments": {}})
    if success_check["type"] == "dom_text_contains":
        result = execute_tool(
            {
                "name": "extract_text",
                "arguments": {"selector": success_check["selector"]},
            }
        )
        state["extracted_text"] = result.get("text") if result.get("success") else None
    return state


def _write_log(record: dict) -> Path:
    """Write one task run's trace, to a filename that cannot collide.

    The run index and a de-duplicating suffix both matter with --repeat:
    the timestamp only has second granularity, and a suite of skipped
    tasks finishes well inside one second, so without these a repeated
    run silently overwrites its own earlier passes.
    """
    LOGS_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    stem = f"{record['task_id']}_{timestamp}_run{record.get('run_index', 0)}"
    path = LOGS_DIR / f"{stem}.json"
    suffix = 2
    while path.exists():
        path = LOGS_DIR / f"{stem}-{suffix}.json"
        suffix += 1
    path.write_text(json.dumps(record, indent=2, default=str))
    return path


def _skipped_record(task: dict, reason: str, run_index: int) -> dict:
    """A task that could not be measured, recorded as neither pass nor fail.

    `passed` and `self_report_correct` are None rather than False on
    purpose: an unreachable site says nothing about the agent, and folding
    it into a pass rate as a failure is exactly the mistake that made
    Milestone 7's A/B comparison meaningless.
    """
    record = {
        "task_id": task["id"],
        "run_index": run_index,
        "passed": None,
        "skipped": reason,
        "self_report": None,
        "self_report_correct": None,
        "steps": 0,
        "wall_clock_seconds": 0.0,
        "routing_enabled": None,
        "routing_checks": 0,
        "final_state": {},
        "trace": [],
    }
    record["log_path"] = str(_write_log(record))
    return record


def run_and_score(task: dict, use_routing: bool = True, run_index: int = 0) -> dict:
    skip_reason = task_skip_reason(task)
    if skip_reason is not None:
        return _skipped_record(task, skip_reason, run_index)

    started_at = time.monotonic()
    loop_result = run_task(
        task["instruction"],
        max_steps=task.get("max_steps", DEFAULT_MAX_STEPS),
        use_routing=use_routing,
    )
    final_state = _fetch_final_state(task["success_check"])
    passed = score_task(task, final_state)
    self_reported_done = loop_result["outcome"] == "done"

    record = {
        "task_id": task["id"],
        "run_index": run_index,
        "passed": passed,
        "skipped": None,
        "self_report": loop_result["outcome"],
        "self_report_correct": self_reported_done == passed,
        "steps": loop_result["steps"],
        "wall_clock_seconds": round(time.monotonic() - started_at, 1),
        "routing_enabled": loop_result.get("routing_enabled", use_routing),
        "routing_checks": loop_result.get("routing_checks", 0),
        "final_state": final_state,
        "trace": loop_result["trace"],
    }
    record["log_path"] = str(_write_log(record))
    return record


def run_suite(
    tasks_dir: Path | str = TASKS_DIR,
    use_routing: bool = True,
    run_index: int = 0,
) -> list[dict]:
    return [
        run_and_score(task, use_routing=use_routing, run_index=run_index)
        for task in load_tasks(tasks_dir)
    ]


def run_suite_repeated(
    tasks_dir: Path | str = TASKS_DIR,
    use_routing: bool = True,
    repeat: int = 1,
) -> list[list[dict]]:
    """Run the whole suite `repeat` times, one list of records per pass.

    Milestone 7 measured this suite at anywhere from 2/7 to 7/7 across six
    runs of identical code, so a single pass is not a measurement. Every
    number this project reports should come from several passes with the
    spread stated alongside it.
    """
    return [
        run_suite(tasks_dir, use_routing=use_routing, run_index=index)
        for index in range(repeat)
    ]


def summarise(runs: list[list[dict]]) -> str:
    """Human-readable summary of one or more suite passes.

    Skipped tasks are held apart from pass/fail everywhere here, and a
    pass rate is printed as a fraction of what was actually *scored*, not
    of what was attempted, so an outage shrinks the denominator instead of
    silently depressing the rate.
    """
    lines = []
    per_run_rates = []
    for index, records in enumerate(runs):
        scored = [r for r in records if r["skipped"] is None]
        skipped = [r for r in records if r["skipped"] is not None]
        passed = sum(1 for r in scored if r["passed"])
        correct = sum(1 for r in scored if r["self_report_correct"])
        label = f"run {index + 1}/{len(runs)}" if len(runs) > 1 else "run"
        if not scored:
            lines.append(f"{label}: NO RESULT, all {len(skipped)} tasks skipped")
        else:
            per_run_rates.append(passed / len(scored))
            lines.append(
                f"{label}: {passed}/{len(scored)} passed, "
                f"{correct}/{len(scored)} self-reports correct, "
                f"{sum(r['steps'] for r in scored)} steps, "
                f"{round(sum(r['wall_clock_seconds'] for r in scored), 1)}s"
                + (f", {len(skipped)} skipped" if skipped else "")
            )
        for record in records:
            if record["skipped"] is not None:
                marker = "SKIP"
                detail = record["skipped"]
            else:
                marker = "PASS" if record["passed"] else "FAIL"
                detail = (
                    f"self-report: {record['self_report']}, "
                    f"steps: {record['steps']}, "
                    f"{record['wall_clock_seconds']}s, "
                    f"routing checks: {record['routing_checks']}"
                )
            lines.append(f"    [{marker}] {record['task_id']} ({detail})")

    if len(runs) > 1:
        lines.append("")
        lines.append("per-task pass rate across runs:")
        for task_id in dict.fromkeys(r["task_id"] for run in runs for r in run):
            attempts = [r for run in runs for r in run if r["task_id"] == task_id]
            scored = [r for r in attempts if r["skipped"] is None]
            skipped_count = len(attempts) - len(scored)
            if not scored:
                lines.append(
                    f"    {task_id}: no result, skipped {skipped_count}/{len(attempts)}"
                )
                continue
            passes = sum(1 for r in scored if r["passed"])
            note = f", {skipped_count} skipped" if skipped_count else ""
            lines.append(
                f"    {task_id}: {passes}/{len(scored)} "
                f"({passes / len(scored):.0%}){note}"
            )
        if per_run_rates:
            lines.append("")
            lines.append(
                f"suite pass rate over {len(per_run_rates)} scored runs: "
                f"min {min(per_run_rates):.0%}, max {max(per_run_rates):.0%}, "
                f"mean {sum(per_run_rates) / len(per_run_rates):.0%}"
            )
            if min(per_run_rates) != max(per_run_rates):
                lines.append(
                    "    the spread is the point: a single run of this suite is "
                    "not a measurement"
                )
    return "\n".join(lines)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--no-routing",
        action="store_true",
        help=(
            "disable the same-failure checkpoint, falling back to Milestone "
            "6's exact-match-only stuck detection (used for the A/B "
            "comparison in docs/milestones/07-model-routing.md)"
        ),
    )
    parser.add_argument(
        "--repeat",
        type=int,
        default=1,
        metavar="N",
        help=(
            "run the whole suite N times and report the per-task pass rate "
            "and the spread across runs. This suite measured anywhere from "
            "2/7 to 7/7 across six runs of identical code, so N=1 does not "
            "support a conclusion"
        ),
    )
    args = parser.parse_args()
    if args.repeat < 1:
        parser.error("--repeat must be at least 1")

    runs = run_suite_repeated(use_routing=not args.no_routing, repeat=args.repeat)
    print(f"\nrouting: {'off' if args.no_routing else 'on'}")
    print(summarise(runs))
