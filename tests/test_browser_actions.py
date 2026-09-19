"""Automated tests for BrowserSession, against a local static HTML fixture
so they run fast and do not depend on network access or a live site.
"""

from pathlib import Path

import pytest

from browser.actions import BrowserSession

FIXTURE_URL = f"file://{Path(__file__).parent / 'fixtures' / 'sample_page.html'}"


@pytest.fixture
async def session():
    s = BrowserSession()
    await s.start()
    yield s
    await s.close()


async def test_navigate_returns_page_summary(session):
    result = await session.navigate(FIXTURE_URL)
    assert result["success"] is True
    assert result["title"] == "Fixture Page"
    assert "Fixture Page" in result["headings"]


async def test_navigate_reports_failure_for_bad_url(session):
    result = await session.navigate("http://localhost:1/definitely-not-listening")
    assert result["success"] is False
    assert "error" in result


async def test_click_by_selector_reveals_hidden_content(session):
    await session.navigate(FIXTURE_URL)
    result = await session.click(selector="#reveal-btn")
    assert result["success"] is True
    revealed = await session.extract_text("#revealed")
    assert revealed["text"] == "Revealed content"


async def test_click_by_text(session):
    await session.navigate(FIXTURE_URL)
    result = await session.click(text="Reveal")
    assert result["success"] is True


async def test_click_without_selector_or_text_fails(session):
    result = await session.click()
    assert result["success"] is False


async def test_click_no_matching_element_fails_gracefully(session):
    await session.navigate(FIXTURE_URL)
    result = await session.click(selector="#does-not-exist")
    assert result["success"] is False
    assert "error" in result


async def test_type_text_fills_input(session):
    await session.navigate(FIXTURE_URL)
    result = await session.type_text("#name-input", "Ada Lovelace")
    assert result["success"] is True
    value = await session.page.locator("#name-input").input_value()
    assert value == "Ada Lovelace"


async def test_extract_text(session):
    await session.navigate(FIXTURE_URL)
    result = await session.extract_text("#greeting")
    assert result["success"] is True
    assert result["text"] == "Hello, world"


async def test_screenshot_returns_base64_png(session):
    await session.navigate(FIXTURE_URL)
    result = await session.screenshot()
    assert result["success"] is True
    assert len(result["image_base64"]) > 0


async def test_wait_for_visible_element(session):
    await session.navigate(FIXTURE_URL)
    result = await session.wait_for("#delayed", timeout_ms=2000)
    assert result["success"] is True


async def test_wait_for_times_out_on_missing_element(session):
    await session.navigate(FIXTURE_URL)
    result = await session.wait_for("#never-appears", timeout_ms=200)
    assert result["success"] is False


async def test_handle_dialog_accept(session):
    await session.navigate(FIXTURE_URL)
    await session.handle_dialog("accept")
    await session.click(selector="#confirm-btn")
    outcome = await session.extract_text("#confirm-result")
    assert outcome["text"] == "accepted"


async def test_handle_dialog_dismiss(session):
    await session.navigate(FIXTURE_URL)
    await session.handle_dialog("dismiss")
    await session.click(selector="#confirm-btn")
    outcome = await session.extract_text("#confirm-result")
    assert outcome["text"] == "dismissed"


async def test_handle_dialog_rejects_unknown_action(session):
    result = await session.handle_dialog("nonsense")
    assert result["success"] is False


async def test_get_page_state(session):
    await session.navigate(FIXTURE_URL)
    state = await session.get_page_state()
    assert state["url"].endswith("sample_page.html")
    assert state["title"] == "Fixture Page"
    assert "Fixture Page" in state["headings"]
