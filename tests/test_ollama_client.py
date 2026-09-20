"""Unit tests for agent/ollama_client.py: the structured-JSON fallback
parser, and the /api/chat wrapper's return shape."""

from agent import ollama_client
from agent.ollama_client import extract_tool_call, ollama_chat

TOOL_NAMES = {"navigate", "click", "report_done"}


class _FakeResponse:
    def __init__(self, json_body: dict):
        self._json_body = json_body

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return self._json_body


def test_ollama_chat_returns_the_full_response_not_just_the_message(monkeypatch):
    """prompt_eval_count and eval_count live alongside `message` at the
    top level of Ollama's response, not inside it. agent/loop.py's token
    accounting (docs/ai-infra-and-observability.md's item 3) needs both,
    so ollama_chat must not throw them away the way it used to when it
    returned only response.json()["message"]."""
    monkeypatch.setattr(
        ollama_client.httpx,
        "post",
        lambda *a, **k: _FakeResponse(
            {
                "message": {"content": "hi"},
                "prompt_eval_count": 42,
                "eval_count": 7,
            }
        ),
    )

    response = ollama_chat("qwen2.5-coder:14b", [{"role": "user", "content": "hi"}])

    assert response["message"] == {"content": "hi"}
    assert response["prompt_eval_count"] == 42
    assert response["eval_count"] == 7


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


def test_falls_back_to_json_in_an_unterminated_markdown_fence():
    """Regression from Milestone 8's first full-suite run: the model opened
    a ```json fence, emitted a complete object, and never closed the fence.
    The parser required the closing fence, so it rejected the whole thing
    and two tasks died on step 0 with "no parseable tool call". Content is
    the exact string from logs/task_03_saucedemo_add_to_cart (2026-09-17)."""
    message = {
        "content": (
            '```json\n{"name": "navigate", "arguments": '
            '{"url": "https://www.saucedemo.com/"}}'
        )
    }

    assert extract_tool_call(message, TOOL_NAMES) == {
        "name": "navigate",
        "arguments": {"url": "https://www.saucedemo.com/"},
    }


def test_falls_back_to_json_in_a_fence_with_no_language_tag():
    message = {"content": '```\n{"name": "click", "arguments": {"text": "Go"}}'}

    assert extract_tool_call(message, TOOL_NAMES) == {
        "name": "click",
        "arguments": {"text": "Go"},
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
