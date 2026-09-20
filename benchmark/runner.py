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


# Checks that read the agent's own report rather than the browser. These
# need care, because this project's whole scoring principle is that the
# model's self-report never decides pass/fail.
#
# `report_contains` does not break that principle: it asserts a specific
# known-correct value scraped from the page by hand beforehand (an email
# address, a page count), so it cannot be satisfied by an agent merely
# claiming success. It is the plan's own "extracted-value assertion", and
# there is no alternative for an extraction task, since the answer lives in
# what the agent read rather than in where the browser ended up.
#
# `agent_reports_blocked` and `agent_asks_for_clarification` are different:
# for the negative-test tier the correct *behavior* is the outcome itself,
# so the agent's report is legitimately the thing under test. For those
# tasks the self-report-accuracy metric is circular and is recorded as
# None rather than as a meaningless number (see _self_report_correct).
REPORT_CHECK_TYPES = {
    "report_contains",
    "agent_reports_blocked",
    "agent_asks_for_clarification",
}

# Checks reading the browser's final state instead of the agent's report.
BROWSER_CHECK_TYPES = {"url_contains", "url_equals", "dom_text_contains"}

# Every check type score_task understands. Exported so a typo in a task
# YAML fails in the test suite rather than part-way through a live run.
KNOWN_CHECK_TYPES = BROWSER_CHECK_TYPES | REPORT_CHECK_TYPES

# Check types needing an `expected` value to compare against. The
# negative-tier checks do not: the expected outcome is the check itself.
CHECK_TYPES_NEEDING_EXPECTED = BROWSER_CHECK_TYPES | {"report_contains"}


def score_task(
    task: dict, final_browser_state: dict, agent_report: dict | None = None
) -> bool:
    """Programmatic pass/fail for one task run.

    `final_browser_state` is whatever _fetch_final_state gathered after the
    loop ended: always the page's url/title/headings, plus `extracted_text`
    when the task's check needs it. `agent_report` is the loop's own
    result (`outcome` and `summary`), needed only by the check types in
    REPORT_CHECK_TYPES above. Kept as a plain dicts-in, bool-out function
    (no browser calls of its own) so it's trivial to unit test.
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

    if check_type in REPORT_CHECK_TYPES:
        if agent_report is None:
            raise ValueError(f"{check_type!r} needs the agent's report to score")
        if check_type == "agent_reports_blocked":
            return agent_report.get("outcome") == "blocked"
        if check_type == "agent_asks_for_clarification":
            return agent_report.get("outcome") == "needs_clarification"
        # report_contains: the agent has to have both finished and said the
        # right value. A blocked run that happens to mention the answer in
        # its reason has not completed an extraction task.
        if agent_report.get("outcome") != "done":
            return False
        summary = (agent_report.get("summary") or "").casefold()
        return str(check["expected"]).casefold() in summary

    raise ValueError(f"unknown success_check type: {check_type!r}")


def _self_report_correct(task: dict, passed: bool, outcome: str) -> bool | None:
    """Did the agent's own claim about its success match reality?

    None for the negative-test tier, where the task's success condition
    *is* the agent's report, so comparing the two would always agree and
    the metric would say nothing. Reporting None is more honest than
    reporting a 100% that was true by construction.
    """
    if task["success_check"]["type"] in {
        "agent_reports_blocked",
        "agent_asks_for_clarification",
    }:
        return None
    return (outcome == "done") == passed


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
        "model_seconds_total": 0.0,
        "tool_seconds_total": 0.0,
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
    agent_report = {
        "outcome": loop_result["outcome"],
        "summary": loop_result.get("summary"),
    }
    passed = score_task(task, final_state, agent_report)

    record = {
        "task_id": task["id"],
        "run_index": run_index,
        "passed": passed,
        "skipped": None,
        "self_report": loop_result["outcome"],
        "self_report_summary": loop_result.get("summary"),
        "self_report_correct": _self_report_correct(
            task, passed, loop_result["outcome"]
        ),
        "steps": loop_result["steps"],
        "wall_clock_seconds": round(time.monotonic() - started_at, 1),
        "routing_enabled": loop_result.get("routing_enabled", use_routing),
        "routing_checks": loop_result.get("routing_checks", 0),
        "model_seconds_total": loop_result.get("model_seconds_total", 0.0),
        "tool_seconds_total": loop_result.get("tool_seconds_total", 0.0),
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
        # Negative-test tasks record None here, because their success
        # condition *is* the agent's own report, so they are excluded from
        # the denominator rather than counted as wrong.
        judged = [r for r in scored if r["self_report_correct"] is not None]
        correct = sum(1 for r in judged if r["self_report_correct"])
        label = f"run {index + 1}/{len(runs)}" if len(runs) > 1 else "run"
        if not scored:
            lines.append(f"{label}: NO RESULT, all {len(skipped)} tasks skipped")
        else:
            per_run_rates.append(passed / len(scored))
            lines.append(
                f"{label}: {passed}/{len(scored)} passed, "
                f"{correct}/{len(judged)} self-reports correct, "
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
