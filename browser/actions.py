"""Playwright-backed browser actions, the tool executor's core logic.

Kept separate from server.py so it can be tested directly against a real
page without going through the HTTP layer. Every method returns a result
dict with a "success" key rather than raising, since the agent's
self-correction loop needs failures fed back as observations, not
exceptions that would crash the loop.
"""

from __future__ import annotations

import base64

from playwright.async_api import Browser, Dialog, Page, Playwright, async_playwright
from playwright.async_api import Error as PlaywrightError

MAX_SUMMARY_ITEMS = 8
DEFAULT_ACTION_TIMEOUT_MS = 5000
INTERACTIVE_SELECTOR = (
    "button, a, input[type=submit], input[type=button], [role=button]"
)


class BrowserSession:
    def __init__(self) -> None:
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._page: Page | None = None
        self._next_dialog_action: str = "dismiss"

    async def start(self) -> None:
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch()
        self._page = await self._browser.new_page()
        self._page.on("dialog", self._on_dialog)

    async def close(self) -> None:
        if self._browser is not None:
            await self._browser.close()
        if self._playwright is not None:
            await self._playwright.stop()

    @property
    def page(self) -> Page:
        if self._page is None:
            raise RuntimeError("BrowserSession.start() was not called")
        return self._page

    async def _on_dialog(self, dialog: Dialog) -> None:
        if self._next_dialog_action == "accept":
            await dialog.accept()
        else:
            await dialog.dismiss()

    async def _summary(self) -> dict:
        page = self.page
        headings = await page.locator("h1, h2, h3").all_inner_texts()
        clickable = await page.locator(
            "button, a, input[type=submit]"
        ).all_inner_texts()
        return {
            "title": await page.title(),
            "url": page.url,
            "headings": [h.strip() for h in headings if h.strip()][:MAX_SUMMARY_ITEMS],
            "clickable": [c.strip() for c in clickable if c.strip()][
                :MAX_SUMMARY_ITEMS
            ],
        }

    async def navigate(self, url: str) -> dict:
        try:
            await self.page.goto(url, wait_until="domcontentloaded")
        except PlaywrightError as e:
            return {"success": False, "error": str(e)}
        return {"success": True, **await self._summary()}

    async def click(self, selector: str | None = None, text: str | None = None) -> dict:
        if selector:
            locator = self.page.locator(selector)
        elif text:
            # Matching by text is meant for "click the button/link labeled
            # X", so prefer an actual clickable element containing that
            # text over any element with matching text (e.g. a heading).
            # Milestone 6 found the-internet.herokuapp.com/login has a
            # "Login Page" heading before the "Login" submit button, so a
            # bare get_by_text(text).first clicked the heading instead.
            interactive = self.page.locator(INTERACTIVE_SELECTOR).filter(has_text=text)
            locator = (
                interactive
                if await interactive.count() > 0
                else self.page.get_by_text(text, exact=False)
            )
        else:
            return {"success": False, "error": "click requires a selector or text"}
        try:
            await locator.first.click(timeout=DEFAULT_ACTION_TIMEOUT_MS)
        except PlaywrightError as e:
            return {
                "success": False,
                "error": f"no clickable element matched selector={selector!r} text={text!r}: {e}",
            }
        return {"success": True, **await self._summary()}

    async def type_text(self, selector: str, text: str) -> dict:
        try:
            await self.page.locator(selector).first.fill(
                text, timeout=DEFAULT_ACTION_TIMEOUT_MS
            )
        except PlaywrightError as e:
            return {
                "success": False,
                "error": f"no input matched selector={selector!r}: {e}",
            }
        return {"success": True}

    async def extract_text(self, selector: str) -> dict:
        try:
            content = await self.page.locator(selector).first.inner_text(
                timeout=DEFAULT_ACTION_TIMEOUT_MS
            )
        except PlaywrightError as e:
            return {
                "success": False,
                "error": f"no element matched selector={selector!r}: {e}",
            }
        return {"success": True, "text": content}

    async def screenshot(self) -> dict:
        data = await self.page.screenshot(type="png")
        return {"success": True, "image_base64": base64.b64encode(data).decode("ascii")}

    async def wait_for(
        self, selector: str, timeout_ms: int = DEFAULT_ACTION_TIMEOUT_MS
    ) -> dict:
        try:
            await self.page.locator(selector).first.wait_for(
                state="visible", timeout=timeout_ms
            )
        except PlaywrightError as e:
            return {
                "success": False,
                "error": f"timed out waiting for selector={selector!r}: {e}",
            }
        return {"success": True}

    async def handle_dialog(self, action: str) -> dict:
        if action not in {"accept", "dismiss"}:
            return {
                "success": False,
                "error": f"unknown dialog action {action!r}, expected accept or dismiss",
            }
        self._next_dialog_action = action
        return {"success": True}

    async def get_page_state(self) -> dict:
        page = self.page
        headings = await page.locator("h1, h2, h3").all_inner_texts()
        return {
            "url": page.url,
            "title": await page.title(),
            "headings": [h.strip() for h in headings if h.strip()][:MAX_SUMMARY_ITEMS],
        }
