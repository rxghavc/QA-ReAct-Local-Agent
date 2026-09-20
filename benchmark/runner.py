"""Loads YAML task definitions, runs the agent against each, scores, and logs."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path

import yaml

from agent.loop import run_task
from agent.tools import execute_tool

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
    LOGS_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = LOGS_DIR / f"{record['task_id']}_{timestamp}.json"
    path.write_text(json.dumps(record, indent=2, default=str))
    return path


def run_and_score(task: dict) -> dict:
    started_at = time.monotonic()
    loop_result = run_task(
        task["instruction"], max_steps=task.get("max_steps", DEFAULT_MAX_STEPS)
    )
    final_state = _fetch_final_state(task["success_check"])
    passed = score_task(task, final_state)
    self_reported_done = loop_result["outcome"] == "done"

    record = {
        "task_id": task["id"],
        "passed": passed,
        "self_report": loop_result["outcome"],
        "self_report_correct": self_reported_done == passed,
        "steps": loop_result["steps"],
        "wall_clock_seconds": round(time.monotonic() - started_at, 1),
        "final_state": final_state,
        "trace": loop_result["trace"],
    }
    record["log_path"] = str(_write_log(record))
    return record


def run_suite(tasks_dir: Path | str = TASKS_DIR) -> list[dict]:
    return [run_and_score(task) for task in load_tasks(tasks_dir)]


if __name__ == "__main__":
    results = run_suite()
    passed = sum(1 for r in results if r["passed"])
    self_report_correct = sum(1 for r in results if r["self_report_correct"])
    print(f"\n{passed}/{len(results)} tasks passed")
    print(
        f"{self_report_correct}/{len(results)} self-reports matched the real outcome\n"
    )
    for r in results:
        marker = "PASS" if r["passed"] else "FAIL"
        print(
            f"  [{marker}] {r['task_id']} "
            f"(self-report: {r['self_report']}, steps: {r['steps']}, {r['wall_clock_seconds']}s)"
        )
