"""Unit tests for benchmark/runner.py and benchmark/report.py."""

import json

import pytest

from benchmark import report, runner


def test_load_tasks_reads_the_real_task_suite():
    tasks = runner.load_tasks()
    task_ids = {task["id"] for task in tasks}

    assert task_ids == {
        "task_01_the_internet_login",
        "task_02_saucedemo_login",
        "task_03_saucedemo_add_to_cart",
        "task_04_saucedemo_checkout",
        "task_05_saucedemo_logout",
    }
    for task in tasks:
        assert "instruction" in task
        assert task["success_check"]["type"] in {
            "url_contains",
            "url_equals",
            "dom_text_contains",
        }


def test_score_task_url_contains():
    task = {"success_check": {"type": "url_contains", "expected": "/secure"}}
    assert runner.score_task(task, {"url": "https://x.test/secure"}) is True
    assert runner.score_task(task, {"url": "https://x.test/login"}) is False


def test_score_task_url_equals():
    task = {"success_check": {"type": "url_equals", "expected": "https://x.test/"}}
    assert runner.score_task(task, {"url": "https://x.test/"}) is True
    assert runner.score_task(task, {"url": "https://x.test/inventory.html"}) is False


def test_score_task_dom_text_contains():
    task = {
        "success_check": {
            "type": "dom_text_contains",
            "selector": ".title",
            "expected": "Products",
        }
    }
    assert runner.score_task(task, {"extracted_text": "Products"}) is True
    assert runner.score_task(task, {"extracted_text": None}) is False
    assert runner.score_task(task, {}) is False


def test_score_task_raises_on_unknown_check_type():
    task = {"success_check": {"type": "not_a_real_check"}}
    with pytest.raises(ValueError, match="not_a_real_check"):
        runner.score_task(task, {})


def test_run_and_score_writes_a_log_and_uses_the_final_browser_state(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(runner, "LOGS_DIR", tmp_path)
    monkeypatch.setattr(
        runner,
        "run_task",
        lambda instruction, max_steps: {"outcome": "done", "steps": 3, "trace": []},
    )

    def fake_execute_tool(call):
        if call["name"] == "get_page_state":
            return {"url": "https://x.test/secure", "title": "Secure", "headings": []}
        raise AssertionError(f"unexpected tool call {call}")

    monkeypatch.setattr(runner, "execute_tool", fake_execute_tool)

    task = {
        "id": "task_test",
        "instruction": "do a thing",
        "success_check": {"type": "url_contains", "expected": "/secure"},
    }
    record = runner.run_and_score(task)

    assert record["passed"] is True
    assert record["self_report"] == "done"
    assert record["self_report_correct"] is True

    logged_files = list(tmp_path.glob("task_test_*.json"))
    assert len(logged_files) == 1
    assert json.loads(logged_files[0].read_text())["task_id"] == "task_test"


def test_run_and_score_flags_a_false_report_done(monkeypatch, tmp_path):
    monkeypatch.setattr(runner, "LOGS_DIR", tmp_path)
    monkeypatch.setattr(
        runner,
        "run_task",
        lambda instruction, max_steps: {"outcome": "done", "steps": 2, "trace": []},
    )
    monkeypatch.setattr(
        runner,
        "execute_tool",
        lambda call: {"url": "https://x.test/login", "title": "", "headings": []},
    )

    task = {
        "id": "task_test",
        "instruction": "do a thing",
        "success_check": {"type": "url_contains", "expected": "/secure"},
    }
    record = runner.run_and_score(task)

    assert record["passed"] is False
    assert record["self_report_correct"] is False


def test_build_report_aggregates_logs(tmp_path):
    for task_id, passed, self_report_correct, steps in [
        ("t1", True, True, 4),
        ("t2", False, False, 15),
    ]:
        record = {
            "task_id": task_id,
            "passed": passed,
            "self_report": "done" if passed else "max_steps",
            "self_report_correct": self_report_correct,
            "steps": steps,
            "wall_clock_seconds": 10.0,
            "final_state": {},
            "trace": [],
        }
        (tmp_path / f"{task_id}.json").write_text(json.dumps(record))

    result = report.build_report(tmp_path)

    assert result["runs"] == 2
    assert result["pass_rate"] == 0.5
    assert result["self_report_accuracy"] == 0.5
    assert result["avg_steps"] == 9.5


def test_build_report_with_no_logs(tmp_path):
    result = report.build_report(tmp_path)
    assert result == {
        "runs": 0,
        "pass_rate": None,
        "self_report_accuracy": None,
        "avg_steps": None,
        "tasks": [],
    }
