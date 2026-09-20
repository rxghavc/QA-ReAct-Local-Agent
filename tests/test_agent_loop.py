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


def test_run_task_hits_max_steps_without_a_terminal_call(monkeypatch):
    monkeypatch.setattr(
        loop, "ollama_chat", lambda *a, **k: _json_message("click", {"text": "Next"})
    )
    monkeypatch.setattr(loop, "execute_tool", lambda call: {"success": True})

    result = loop.run_task("do a thing", max_steps=3)

    assert result["outcome"] == "max_steps"
    assert result["steps"] == 3
    assert len(result["trace"]) == 3