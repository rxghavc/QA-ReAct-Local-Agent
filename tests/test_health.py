"""Unit tests for benchmark/health.py's pre-flight site checks.

All network access is monkeypatched out, so these are fast and do not
depend on the very third-party uptime this module exists to guard against.
"""

import httpx
import pytest

from benchmark import health


class _Response:
    def __init__(self, status_code):
        self.status_code = status_code


def _serving(status_code):
    return lambda url, timeout, follow_redirects: _Response(status_code)


def _refusing(exc):
    def raise_it(url, timeout, follow_redirects):
        raise exc

    return raise_it


def test_health_check_url_reads_the_url_out_of_the_instruction():
    task = {
        "instruction": (
            "Go to https://the-internet.herokuapp.com/login, log in with "
            "username 'tomsmith' and password 'SuperSecretPassword!'."
        )
    }
    assert health.health_check_url(task) == "https://the-internet.herokuapp.com/login"


def test_health_check_url_strips_trailing_prose_punctuation():
    assert (
        health.health_check_url(
            {"instruction": "Open https://example.com/x, then stop"}
        )
        == "https://example.com/x"
    )
    assert (
        health.health_check_url({"instruction": "Open https://example.com/x."})
        == "https://example.com/x"
    )


def test_health_check_url_prefers_an_explicit_override():
    task = {
        "instruction": "Go to https://wrong.example/page and do a thing",
        "health_check_url": "https://right.example",
    }
    assert health.health_check_url(task) == "https://right.example"


def test_health_check_url_is_none_when_the_instruction_has_no_url():
    assert health.health_check_url({"instruction": "Buy the cheapest thing"}) is None


@pytest.mark.parametrize("status_code", [200, 204, 302, 399])
def test_check_url_treats_anything_below_400_as_reachable(monkeypatch, status_code):
    """A redirect or a login wall is not an outage. Judging whether the
    page is the *right* page is the scorer's job, not this module's."""
    monkeypatch.setattr(health.httpx, "get", _serving(status_code))
    healthy, detail = health.check_url("https://example.com")
    assert healthy is True
    assert str(status_code) in detail


@pytest.mark.parametrize("status_code", [404, 500, 503])
def test_check_url_treats_4xx_and_5xx_as_unreachable(monkeypatch, status_code):
    monkeypatch.setattr(health.httpx, "get", _serving(status_code))
    healthy, detail = health.check_url("https://example.com")
    assert healthy is False
    assert detail == f"HTTP {status_code}"


def test_check_url_treats_a_transport_error_as_unreachable(monkeypatch):
    monkeypatch.setattr(
        health.httpx, "get", _refusing(httpx.ConnectError("nodename nor servname"))
    )
    healthy, detail = health.check_url("https://nope.invalid")
    assert healthy is False
    assert "ConnectError" in detail


def test_task_skip_reason_skips_a_task_whose_site_is_down(monkeypatch):
    """The Milestone 7 incident: the-internet.herokuapp.com served HTTP 503
    partway through an A/B run and three tasks scored as agent failures."""
    monkeypatch.setattr(health.httpx, "get", _serving(503))
    reason = health.task_skip_reason(
        {"instruction": "Go to https://the-internet.herokuapp.com/login and log in"}
    )
    assert reason is not None
    assert "the-internet.herokuapp.com/login" in reason
    assert "HTTP 503" in reason


def test_task_skip_reason_is_none_when_the_site_is_up(monkeypatch):
    monkeypatch.setattr(health.httpx, "get", _serving(200))
    assert health.task_skip_reason({"instruction": "Go to https://example.com"}) is None


def test_task_skip_reason_is_none_when_there_is_no_url_to_check(monkeypatch):
    """A task that is not about reaching a particular site, such as an
    ambiguous-instruction negative test, has nothing to pre-flight and
    must not be skipped for it."""

    def fail_if_called(*args, **kwargs):
        raise AssertionError("no health request should be made without a URL")

    monkeypatch.setattr(health.httpx, "get", fail_if_called)
    assert health.task_skip_reason({"instruction": "Buy something nice"}) is None
