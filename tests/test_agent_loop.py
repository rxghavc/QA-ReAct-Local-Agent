"""Unit tests for agent/loop.py's ReAct orchestration, with the Ollama and
browser layers mocked out so these don't need a live model or browser.
"""

import json
import time

from agent import loop


def _json_message(
    name: str, arguments: dict, prompt_tokens: int = 0, completion_tokens: int = 0
) -> dict:
    """A mocked ollama_chat return value: the full /api/chat response
    shape (message plus the two top-level token-count fields), not just
    the message, matching what agent/loop.py now reads."""
    return {
        "message": {"content": json.dumps({"name": name, "arguments": arguments})},
        "prompt_eval_count": prompt_tokens,
        "eval_count": completion_tokens,
    }


def test_run_task_ends_with_needs_clarification_on_ask_clarification(monkeypatch):
    """The ambiguous-instruction negative test needs its own outcome:
    "this could mean two things" is a genuinely different answer from
    "I tried and could not", and collapsing it into blocked would make
    that task unscoreable without keyword-sniffing the reason."""
    monkeypatch.setattr(
        loop,
        "ollama_chat",
        lambda *a, **k: _json_message(
            "ask_clarification", {"question": "Best by rating or by price?"}
        ),
    )

    def fail_if_called(call):
        raise AssertionError("a terminal tool must not be sent to the browser")

    monkeypatch.setattr(loop, "execute_tool", fail_if_called)

    result = loop.run_task("add the best book", max_steps=5)

    assert result["outcome"] == "needs_clarification"
    assert result["summary"] == "Best by rating or by price?"
    assert result["steps"] == 1


def test_every_terminal_tool_maps_to_a_distinct_outcome():
    """Two terminal tools sharing an outcome would silently merge the
    negative tiers into one unscoreable bucket."""
    outcomes = list(loop.TERMINAL_OUTCOMES.values())
    assert len(set(outcomes)) == len(outcomes)
    assert loop.TERMINAL_TOOLS == set(loop.TERMINAL_OUTCOMES)


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


def test_run_task_tracks_model_and_tool_time_separately(monkeypatch):
    """The observability plan (docs/ai-infra-and-observability.md) needs to
    tell model inference time apart from tool execution time. A deliberate
    sleep on each side, well clear of scheduling jitter, proves the two
    totals are tracking their own side and not double-counting or swapping."""
    responses = [
        _json_message("navigate", {"url": "https://x.test"}),
        _json_message("report_done", {"summary": "done it"}),
    ]

    def slow_chat(*_a, **_k):
        time.sleep(0.2)
        return responses.pop(0)

    def slow_tool(_call):
        time.sleep(0.1)
        return {"success": True, "title": "X"}

    monkeypatch.setattr(loop, "ollama_chat", slow_chat)
    monkeypatch.setattr(loop, "execute_tool", slow_tool)

    result = loop.run_task("do a thing", max_steps=5)

    # Two model calls (navigate's, then report_done's) vs one tool call
    # (navigate's; report_done is terminal and never reaches execute_tool).
    assert result["model_seconds_total"] >= 0.4
    assert result["tool_seconds_total"] >= 0.1
    assert result["tool_seconds_total"] < result["model_seconds_total"]

    navigate_step, report_done_step = result["trace"]
    assert navigate_step["model_seconds"] > 0
    assert navigate_step["tool_seconds"] > 0
    assert report_done_step["model_seconds"] > 0
    assert "tool_seconds" not in report_done_step


def test_run_task_tracks_prompt_and_completion_tokens(monkeypatch):
    """Ollama reports prompt_eval_count/eval_count alongside message on
    every /api/chat call, not inside it (agent/ollama_client.py's
    ollama_chat now returns the whole response for exactly this reason).
    Each step's own counts should show up in its trace entry, and the
    running totals should be the sum across steps, not just the last one."""
    responses = [
        _json_message(
            "navigate",
            {"url": "https://x.test"},
            prompt_tokens=100,
            completion_tokens=20,
        ),
        _json_message(
            "report_done",
            {"summary": "done it"},
            prompt_tokens=150,
            completion_tokens=15,
        ),
    ]
    monkeypatch.setattr(loop, "ollama_chat", lambda *a, **k: responses.pop(0))
    monkeypatch.setattr(
        loop, "execute_tool", lambda call: {"success": True, "title": "X"}
    )

    result = loop.run_task("do a thing", max_steps=5)

    assert result["prompt_tokens_total"] == 250
    assert result["completion_tokens_total"] == 35

    navigate_step, report_done_step = result["trace"]
    assert navigate_step["prompt_tokens"] == 100
    assert navigate_step["completion_tokens"] == 20
    assert report_done_step["prompt_tokens"] == 150
    assert report_done_step["completion_tokens"] == 15


def test_run_task_trims_old_tool_results_when_history_trim_is_set(monkeypatch):
    """agent/history.py's trim_history is wired in, not just importable:
    passing history_trim should actually shrink old tool-result payloads
    in the messages sent to the model, the whole point of
    docs/context-optimization-plan.md's first idea. Off by default
    (other tests here never pass it and see full payloads throughout)."""
    import copy

    responses = [
        _json_message("navigate", {"url": "https://x.test"}),
        _json_message("click", {"text": "Login"}),
        _json_message("report_done", {"summary": "done it"}),
    ]
    captured_messages = []

    def fake_chat(_model, messages, **_kwargs):
        captured_messages.append(copy.deepcopy(messages))
        return responses.pop(0)

    monkeypatch.setattr(loop, "ollama_chat", fake_chat)
    monkeypatch.setattr(
        loop,
        "execute_tool",
        lambda call: {"success": True, "title": "X", "headings": ["Big page dump"]},
    )

    loop.run_task("do a thing", max_steps=5, history_trim="full", history_keep_last=0)

    # Snapshot taken right before the third (report_done) model call: both
    # earlier tool results should already be trimmed to just `success`.
    final_call_messages = captured_messages[-1]
    tool_messages = [m for m in final_call_messages if m.get("role") == "tool"]
    assert len(tool_messages) == 2
    for message in tool_messages:
        assert json.loads(message["content"]) == {"success": True}


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
        loop,
        "ollama_chat",
        lambda *a, **k: {"message": {"content": "I'm not sure what to do."}},
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


def test_run_task_does_not_nudge_when_the_router_says_failures_are_different(
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
    monkeypatch.setattr(loop, "is_same_failure", lambda pc, pe, cc, ce: False)

    result = loop.run_task("do a thing", max_steps=3)

    assert not any(step.get("stuck_nudge") for step in result["trace"])


def test_run_task_nudges_via_routing_when_the_router_says_failures_are_the_same(
    monkeypatch,
):
    calls = [
        _json_message("click", {"selector": ".btn_primary:first-child"}),
        _json_message("click", {"selector": ".inventory_item"}),
    ]
    monkeypatch.setattr(loop, "ollama_chat", lambda *a, **k: calls.pop(0))
    monkeypatch.setattr(
        loop, "execute_tool", lambda call: {"success": False, "error": "no match"}
    )
    router_calls = []
    monkeypatch.setattr(
        loop,
        "is_same_failure",
        lambda pc, pe, cc, ce: router_calls.append((pc, cc)) or True,
    )

    result = loop.run_task("do a thing", max_steps=2)

    assert any(step.get("stuck_nudge") for step in result["trace"])
    assert len(router_calls) == 1
    assert result["routing_checks"] == 1
    assert result["routing_enabled"] is True


def test_run_task_nudges_on_the_real_checkout_failure_without_mocking_routing(
    monkeypatch,
):
    """End to end through the real agent.routing.is_same_failure, on the
    exact pair that the rejected llama3.2:3b classifier got wrong during
    the 2026-09-17 benchmark run: two clicks on the same checkout button
    differing only in capitalisation. Exact-match stuck detection can
    never catch this, because no two attempts are identical."""
    calls = [
        _json_message("click", {"text": "Checkout"}),
        _json_message("click", {"text": "CHECKOUT"}),
    ]
    monkeypatch.setattr(loop, "ollama_chat", lambda *a, **k: calls.pop(0))
    monkeypatch.setattr(
        loop,
        "execute_tool",
        lambda call: {
            "success": False,
            "error": f"no clickable element matched text={call['arguments']['text']!r}",
        },
    )

    result = loop.run_task("complete checkout", max_steps=2)

    assert any(step.get("stuck_nudge") for step in result["trace"])
    assert result["routing_checks"] == 1


def test_run_task_never_calls_the_router_when_routing_is_disabled(monkeypatch):
    calls = [
        _json_message("click", {"selector": "#a"}),
        _json_message("click", {"selector": "#b"}),
    ]
    monkeypatch.setattr(loop, "ollama_chat", lambda *a, **k: calls.pop(0))
    monkeypatch.setattr(
        loop, "execute_tool", lambda call: {"success": False, "error": "no match"}
    )

    def fail_if_called(pc, pe, cc, ce):
        raise AssertionError("is_same_failure should not be called when routing is off")

    monkeypatch.setattr(loop, "is_same_failure", fail_if_called)

    result = loop.run_task("do a thing", max_steps=2, use_routing=False)

    assert not any(step.get("stuck_nudge") for step in result["trace"])
    assert result["routing_enabled"] is False
    assert result["routing_checks"] == 0


def test_run_task_hits_max_steps_without_a_terminal_call(monkeypatch):
    monkeypatch.setattr(
        loop, "ollama_chat", lambda *a, **k: _json_message("click", {"text": "Next"})
    )
    monkeypatch.setattr(loop, "execute_tool", lambda call: {"success": True})

    result = loop.run_task("do a thing", max_steps=3)

    assert result["outcome"] == "max_steps"
    assert result["steps"] == 3
    assert len(result["trace"]) == 3
