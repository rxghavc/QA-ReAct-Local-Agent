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
        "task_06_dynamic_loading",
        "task_07_js_confirm_dialog",
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
        lambda instruction, max_steps, use_routing: {
            "outcome": "done",
            "steps": 3,
            "trace": [],
            "routing_enabled": use_routing,
            "routing_checks": 0,
        },
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
        lambda instruction, max_steps, use_routing: {
            "outcome": "done",
            "steps": 2,
            "trace": [],
            "routing_enabled": use_routing,
            "routing_checks": 0,
        },
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


def test_run_and_score_skips_a_task_whose_site_is_unreachable(monkeypatch, tmp_path):
    """The whole point of the pre-flight check: an unreachable site must
    not be recorded as a failing agent, and the loop must not even run."""
    monkeypatch.setattr(runner, "LOGS_DIR", tmp_path)
    monkeypatch.setattr(
        runner, "task_skip_reason", lambda task: "example.com down (HTTP 503)"
    )

    def fail_if_called(*args, **kwargs):
        raise AssertionError("the agent must not run when the site is down")

    monkeypatch.setattr(runner, "run_task", fail_if_called)
    monkeypatch.setattr(runner, "execute_tool", fail_if_called)

    record = runner.run_and_score(
        {
            "id": "task_x",
            "instruction": "Go to https://example.com",
            "success_check": {"type": "url_contains", "expected": "/x"},
        }
    )

    assert record["passed"] is None
    assert record["self_report_correct"] is None
    assert record["skipped"] == "example.com down (HTTP 503)"
    assert record["steps"] == 0
    assert record["trace"] == []


def test_run_suite_repeated_runs_every_task_once_per_pass(monkeypatch, tmp_path):
    monkeypatch.setattr(runner, "LOGS_DIR", tmp_path)
    monkeypatch.setattr(runner, "task_skip_reason", lambda task: None)
    monkeypatch.setattr(
        runner,
        "load_tasks",
        lambda tasks_dir: [
            {
                "id": "a",
                "instruction": "i",
                "success_check": {"type": "url_contains", "expected": "/"},
            },
            {
                "id": "b",
                "instruction": "i",
                "success_check": {"type": "url_contains", "expected": "/"},
            },
        ],
    )
    monkeypatch.setattr(
        runner,
        "run_task",
        lambda instruction, max_steps, use_routing: {
            "outcome": "done",
            "steps": 1,
            "trace": [],
            "routing_enabled": use_routing,
            "routing_checks": 0,
        },
    )
    monkeypatch.setattr(runner, "_fetch_final_state", lambda check: {"url": "/"})

    runs = runner.run_suite_repeated(repeat=3)

    assert [len(run) for run in runs] == [2, 2, 2]
    assert [r["run_index"] for run in runs for r in run] == [0, 0, 1, 1, 2, 2]


def test_write_log_does_not_let_repeated_runs_overwrite_each_other(
    monkeypatch, tmp_path
):
    """Regression: the log filename only has second granularity, and a
    suite of skipped tasks finishes well inside one second, so --repeat
    was silently overwriting its own earlier passes."""
    monkeypatch.setattr(runner, "LOGS_DIR", tmp_path)

    paths = [
        runner._write_log({"task_id": "t", "run_index": index}) for index in range(3)
    ]

    assert len({p.name for p in paths}) == 3
    assert len(list(tmp_path.glob("*.json"))) == 3


def test_write_log_disambiguates_two_runs_with_the_same_index(monkeypatch, tmp_path):
    monkeypatch.setattr(runner, "LOGS_DIR", tmp_path)

    first = runner._write_log({"task_id": "t", "run_index": 0})
    second = runner._write_log({"task_id": "t", "run_index": 0})

    assert first != second
    assert len(list(tmp_path.glob("*.json"))) == 2


def test_summarise_reports_the_spread_across_repeats():
    """A single aggregate number hides the finding. Milestone 7 measured
    this suite at 2/7 to 7/7 across six runs of identical code."""

    def rec(task_id, passed, run_index):
        return {
            "task_id": task_id,
            "run_index": run_index,
            "passed": passed,
            "skipped": None,
            "self_report": "done" if passed else "blocked",
            "self_report_correct": True,
            "steps": 5,
            "wall_clock_seconds": 1.0,
            "routing_checks": 0,
        }

    runs = [
        [rec("a", True, 0), rec("b", True, 0)],
        [rec("a", True, 1), rec("b", False, 1)],
    ]

    text = runner.summarise(runs)

    assert "run 1/2: 2/2 passed" in text
    assert "run 2/2: 1/2 passed" in text
    assert "a: 2/2 (100%)" in text
    assert "b: 1/2 (50%)" in text
    assert "min 50%, max 100%, mean 75%" in text
    assert "a single run of this suite is not a measurement" in text


def test_summarise_holds_skipped_tasks_apart_from_pass_fail():
    records = [
        {
            "task_id": "up",
            "run_index": 0,
            "passed": True,
            "skipped": None,
            "self_report": "done",
            "self_report_correct": True,
            "steps": 3,
            "wall_clock_seconds": 1.0,
            "routing_checks": 0,
        },
        {
            "task_id": "down",
            "run_index": 0,
            "passed": None,
            "skipped": "site.example unreachable (HTTP 503)",
            "self_report": None,
            "self_report_correct": None,
            "steps": 0,
            "wall_clock_seconds": 0.0,
            "routing_checks": 0,
        },
    ]

    text = runner.summarise([records])

    assert "1/1 passed" in text
    assert "1 skipped" in text
    assert "[SKIP] down (site.example unreachable (HTTP 503))" in text


def test_summarise_says_no_result_when_everything_was_skipped():
    records = [
        {
            "task_id": "down",
            "run_index": 0,
            "passed": None,
            "skipped": "unreachable",
            "self_report": None,
            "self_report_correct": None,
            "steps": 0,
            "wall_clock_seconds": 0.0,
            "routing_checks": 0,
        }
    ]

    assert "NO RESULT, all 1 tasks skipped" in runner.summarise([records])


def _log(tmp_path, name, **overrides):
    record = {
        "task_id": name,
        "run_index": 0,
        "passed": True,
        "skipped": None,
        "self_report": "done",
        "self_report_correct": True,
        "steps": 4,
        "wall_clock_seconds": 10.0,
        "final_state": {},
        "trace": [],
    }
    record.update(overrides)
    (tmp_path / f"{name}_{record['run_index']}.json").write_text(json.dumps(record))


def test_build_report_aggregates_logs(tmp_path):
    _log(tmp_path, "t1", passed=True, self_report_correct=True, steps=4)
    _log(
        tmp_path,
        "t2",
        passed=False,
        self_report="max_steps",
        self_report_correct=False,
        steps=15,
    )

    result = report.build_report(tmp_path)

    assert result["scored"] == 2
    assert result["skipped"] == 0
    assert result["pass_rate"] == 0.5
    assert result["self_report_accuracy"] == 0.5
    assert result["avg_steps"] == 9.5


def test_build_report_excludes_skipped_runs_from_the_pass_rate(tmp_path):
    """A task skipped for an unreachable site was never measured, so it
    shrinks the denominator instead of counting as a failure. Counting it
    as a failure is what made Milestone 7's A/B comparison meaningless."""
    _log(tmp_path, "t1", passed=True)
    _log(tmp_path, "t2", passed=None, skipped="example.com unreachable (HTTP 503)")

    result = report.build_report(tmp_path)

    assert result["logs"] == 2
    assert result["scored"] == 1
    assert result["skipped"] == 1
    assert result["pass_rate"] == 1.0
    assert [t["task_id"] for t in result["tasks"]] == ["t1"]


def test_build_report_gives_no_result_when_every_run_was_skipped(tmp_path):
    _log(tmp_path, "t1", passed=None, skipped="down")
    _log(tmp_path, "t2", passed=None, skipped="down")

    result = report.build_report(tmp_path)

    assert result["logs"] == 2
    assert result["scored"] == 0
    assert result["skipped"] == 2
    assert result["pass_rate"] is None


def test_build_report_reports_a_per_task_pass_rate_across_repeats(tmp_path):
    """The headline reason --repeat exists: one task passing 2 of 3 times
    is the finding, and a single aggregate number hides it."""
    for index, passed in enumerate([True, False, True]):
        _log(tmp_path, "flaky", run_index=index, passed=passed, steps=6)

    result = report.build_report(tmp_path)

    (task,) = result["tasks"]
    assert task["attempts"] == 3
    assert task["passes"] == 2
    assert task["pass_rate"] == 0.67


def test_build_report_treats_pre_skip_field_logs_as_scored(tmp_path):
    """Logs written before the skip field existed predate skipping, so
    they are scored runs by definition."""
    legacy = {
        "task_id": "old",
        "passed": True,
        "self_report": "done",
        "self_report_correct": True,
        "steps": 3,
        "wall_clock_seconds": 5.0,
    }
    (tmp_path / "old.json").write_text(json.dumps(legacy))

    result = report.build_report(tmp_path)

    assert result["scored"] == 1
    assert result["pass_rate"] == 1.0


def test_build_report_ignores_unreadable_logs(tmp_path):
    _log(tmp_path, "good", passed=True)
    (tmp_path / "truncated.json").write_text('{"task_id": "bad", "pas')

    result = report.build_report(tmp_path)

    assert result["scored"] == 1


def test_build_report_with_no_logs(tmp_path):
    result = report.build_report(tmp_path)
    assert result == {
        "logs": 0,
        "scored": 0,
        "skipped": 0,
        "pass_rate": None,
        "self_report_accuracy": None,
        "avg_steps": None,
        "tasks": [],
    }
