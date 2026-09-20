"""Unit tests for agent/history.py."""

import json

from agent.history import trim_history


def _tool_message(**result) -> dict:
    return {"role": "tool", "content": json.dumps(result)}


def _assistant_message() -> dict:
    return {"role": "assistant", "content": '{"name": "click", "arguments": {}}'}


def test_none_policy_leaves_everything_untouched():
    messages = [
        _tool_message(success=True, url="https://x.test", title="X", headings=["A"])
    ]
    trim_history(messages, keep_last=0, policy="none")

    assert json.loads(messages[0]["content"])["headings"] == ["A"]


def test_partial_policy_drops_headings_and_clickable_but_keeps_url_and_title():
    messages = [
        _tool_message(
            success=True,
            url="https://x.test",
            title="X",
            headings=["A"],
            clickable=["B"],
        )
    ]
    trim_history(messages, keep_last=0, policy="partial")

    trimmed = json.loads(messages[0]["content"])
    assert trimmed == {"success": True, "url": "https://x.test", "title": "X"}


def test_full_policy_keeps_only_success_and_error():
    messages = [
        _tool_message(success=False, url="https://x.test", title="X", error="nope")
    ]
    trim_history(messages, keep_last=0, policy="full")

    assert json.loads(messages[0]["content"]) == {"success": False, "error": "nope"}


def test_keep_last_protects_the_most_recent_tool_messages():
    messages = [
        _tool_message(success=True, url="https://old.test", headings=["old"]),
        _assistant_message(),
        _tool_message(success=True, url="https://new.test", headings=["new"]),
    ]
    trim_history(messages, keep_last=1, policy="full")

    assert json.loads(messages[0]["content"]) == {"success": True}
    assert json.loads(messages[2]["content"])["headings"] == ["new"]


def test_keep_last_zero_trims_every_tool_message():
    messages = [
        _tool_message(success=True, headings=["a"]),
        _tool_message(success=True, headings=["b"]),
    ]
    trim_history(messages, keep_last=0, policy="full")

    assert all(json.loads(m["content"]) == {"success": True} for m in messages)


def test_only_tool_role_messages_are_touched():
    messages = [_assistant_message()]
    trim_history(messages, keep_last=0, policy="full")

    assert messages[0]["content"] == '{"name": "click", "arguments": {}}'


def test_unparseable_content_is_left_untouched_rather_than_risking_corruption():
    messages = [{"role": "tool", "content": "not json"}]
    trim_history(messages, keep_last=0, policy="full")

    assert messages[0]["content"] == "not json"


def test_trimming_twice_is_a_no_op():
    messages = [_tool_message(success=True, url="https://x.test", headings=["A"])]
    trim_history(messages, keep_last=0, policy="partial")
    once = messages[0]["content"]
    trim_history(messages, keep_last=0, policy="partial")

    assert messages[0]["content"] == once
