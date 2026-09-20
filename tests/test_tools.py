"""Unit tests for tool dispatch and scoring logic."""

import httpx
import pytest

from agent import tools


class FakeResponse:
    def __init__(self, json_body: dict, status_code: int = 200):
        self._json_body = json_body
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("error", request=None, response=None)

    def json(self) -> dict:
        return self._json_body


def test_execute_tool_posts_arguments_to_the_matching_endpoint(monkeypatch):
    captured = {}

    def fake_post(url, json, timeout):
        captured["url"] = url
        captured["json"] = json
        return FakeResponse({"success": True, "title": "Example"})

    monkeypatch.setattr(tools.httpx, "post", fake_post)

    result = tools.execute_tool(
        {"name": "navigate", "arguments": {"url": "https://example.com"}}
    )

    assert captured["url"] == f"{tools.BROWSER_SERVICE_URL}/navigate"
    assert captured["json"] == {"url": "https://example.com"}
    assert result == {"success": True, "title": "Example"}


def test_execute_tool_uses_get_for_get_page_state(monkeypatch):
    captured = {}

    def fake_get(url, timeout):
        captured["url"] = url
        return FakeResponse(
            {"url": "https://example.com", "title": "Example", "headings": []}
        )

    monkeypatch.setattr(tools.httpx, "get", fake_get)

    result = tools.execute_tool({"name": "get_page_state", "arguments": {}})

    assert captured["url"] == f"{tools.BROWSER_SERVICE_URL}/get_page_state"
    assert result["title"] == "Example"


def test_execute_tool_returns_failure_dict_for_unknown_tool():
    result = tools.execute_tool({"name": "delete_everything", "arguments": {}})
    assert result == {"success": False, "error": "unknown tool 'delete_everything'"}


def test_execute_tool_returns_failure_dict_when_browser_service_unreachable(
    monkeypatch,
):
    def fake_post(url, json, timeout):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(tools.httpx, "post", fake_post)

    result = tools.execute_tool({"name": "click", "arguments": {"text": "Login"}})

    assert result["success"] is False
    assert "browser service request failed" in result["error"]


@pytest.mark.parametrize("tool_name", [t["function"]["name"] for t in tools.TOOLS])
def test_every_declared_tool_is_either_dispatchable_or_terminal(tool_name):
    terminal = {"report_done", "report_blocked"}
    assert tool_name in tools._BROWSER_ENDPOINTS or tool_name in terminal
