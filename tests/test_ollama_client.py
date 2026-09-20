"""Unit tests for the structured-JSON fallback parser in agent/ollama_client.py."""

from agent.ollama_client import extract_tool_call

TOOL_NAMES = {"navigate", "click", "report_done"}


def test_prefers_native_tool_calls():
    message = {
        "content": "",
        "tool_calls": [
            {"function": {"name": "navigate", "arguments": {"url": "https://x.test"}}}
        ],
    }
    assert extract_tool_call(message, TOOL_NAMES) == {
        "name": "navigate",
        "arguments": {"url": "https://x.test"},
    }


def test_falls_back_to_untagged_json_content():
    message = {"content": '{"name": "click", "arguments": {"text": "Login"}}'}
    assert extract_tool_call(message, TOOL_NAMES) == {
        "name": "click",
        "arguments": {"text": "Login"},
    }


def test_falls_back_to_tagged_json_content():
    message = {
        "content": '<tool_call>{"name": "report_done", "arguments": {"summary": "ok"}}</tool_call>'
    }
    assert extract_tool_call(message, TOOL_NAMES) == {
        "name": "report_done",
        "arguments": {"summary": "ok"},
    }


def test_falls_back_to_markdown_fenced_json_content():
    message = {
        "content": '```json\n{"name": "navigate", "arguments": {"url": "https://x.test"}}\n```'
    }
    assert extract_tool_call(message, TOOL_NAMES) == {
        "name": "navigate",
        "arguments": {"url": "https://x.test"},
    }


def test_takes_only_first_json_object_when_model_front_loads_several():
    content = (
        '{"name": "navigate", "arguments": {"url": "https://x.test"}}\n'
        '{"name": "click", "arguments": {"text": "Login"}}'
    )
    assert extract_tool_call({"content": content}, TOOL_NAMES) == {
        "name": "navigate",
        "arguments": {"url": "https://x.test"},
    }


def test_returns_none_for_unparseable_content():
    assert (
        extract_tool_call({"content": "I think I should click the button."}, TOOL_NAMES)
        is None
    )


def test_returns_none_for_unknown_tool_name():
    assert (
        extract_tool_call(
            {"content": '{"name": "delete_everything", "arguments": {}}'}, TOOL_NAMES
        )
        is None
    )
