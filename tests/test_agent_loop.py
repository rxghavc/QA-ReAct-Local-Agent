"""Unit tests for agent/loop.py's ReAct orchestration, with the Ollama and
browser layers mocked out so these don't need a live model or browser.
"""

import json

from agent import loop


def _json_message(name: str, arguments: dict) -> dict:
    return {"content": json.dumps({"name": name, "arguments": arguments})}


def test_run_task_reaches_report_done(monkeypatch):
    responses = [
        _json_message("navigate", {"url": "https://x.test"}),
        _json_message("report_done", {"summary": "done it"}),
    ]
    monkeypatch.setattr(loop, "ollama_chat", lambda *a, **k: responses.pop(0))
    monkeypatch.setattr(
        loop, "execute_tool", lambda call: {"success": True, "title": "X"}
    )

    result = loop.run_task("do a thing", max_steps=5)

    assert result["outcome"] == "done"
    assert result["summary"] == "done it"
    assert result["steps"] == 2
    assert len(result["trace"]) == 2


def test_run_task_reaches_report_blocked(monkeypatch):
    monkeypatch.setattr(
        loop,
        "ollama_chat",
        lambda *a, **k: _json_message("report_blocked", {"reason": "no such element"}),
    )
    monkeypatch.setattr(loop, "execute_tool", lambda call: {"success": False})

    result = loop.run_task("do an impossible thing", max_steps=5)

    assert result["outcome"] == "blocked"
    assert result["summary"] == "no such element"


def test_run_task_stops_when_no_tool_call_parses(monkeypatch):
    monkeypatch.setattr(
        loop, "ollama_chat", lambda *a, **k: {"content": "I'm not sure what to do."}
    )
    monkeypatch.setattr(loop, "execute_tool", lambda call: {"success": False})

    result = loop.run_task("do a thing", max_steps=5)

    assert result["outcome"] == "stuck"
    assert result["steps"] == 1


def test_run_task_injects_a_stuck_nudge_after_repeated_identical_failures(monkeypatch):
    same_call = _json_message("click", {"selector": "#nope"})
    monkeypatch.setattr(loop, "ollama_chat", lambda *a, **k: same_call)
    monkeypatch.setattr(
        loop, "execute_tool", lambda call: {"success": False, "error": "no match"}
    )

    result = loop.run_task("do a thing", max_steps=4)

    nudges = [step for step in result["trace"] if step.get("stuck_nudge")]
    # Fails twice in a row -> nudge and reset -> fails twice more -> nudge again.
    assert len(nudges) == 2
    assert nudges[0]["step"] == 1
    assert nudges[1]["step"] == 3


def test_run_task_does_not_nudge_on_a_single_failure_or_on_success(monkeypatch):
    monkeypatch.setattr(
        loop, "ollama_chat", lambda *a, **k: _json_message("click", {"text": "Login"})
    )
    monkeypatch.setattr(
        loop, "execute_tool", lambda call: {"success": False, "error": "timeout"}
    )

    result = loop.run_task("do a thing", max_steps=1)

    assert not any(step.get("stuck_nudge") for step in result["trace"])


def test_run_task_does_not_nudge_when_failures_alternate_between_different_calls(
    monkeypatch,
):
    calls = [
        _json_message("click", {"selector": "#a"}),
        _json_message("click", {"selector": "#b"}),
        _json_message("click", {"selector": "#a"}),
    ]
    monkeypatch.setattr(loop, "ollama_chat", lambda *a, **k: calls.pop(0))
    monkeypatch.setattr(
        loop, "execute_tool", lambda call: {"success": False, "error": "no match"}
    )

    result = loop.run_task("do a thing", max_steps=3)

    assert not any(step.get("stuck_nudge") for step in result["trace"])


def test_run_task_hits_max_steps_without_a_terminal_call(monkeypatch):
    monkeypatch.setattr(
        loop, "ollama_chat", lambda *a, **k: _json_message("click", {"text": "Next"})
    )
    monkeypatch.setattr(loop, "execute_tool", lambda call: {"success": True})

    result = loop.run_task("do a thing", max_steps=3)

    assert result["outcome"] == "max_steps"
    assert result["steps"] == 3
    assert len(result["trace"]) == 3
