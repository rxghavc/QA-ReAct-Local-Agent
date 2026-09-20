# Milestone 2: Building the browser control layer

## What this milestone was actually building

Milestone 1 answered "can a local model reliably say what it wants to do next." Milestone 2 answers a completely separate question: "given that the model says 'click the button labeled Login', what actually makes that happen in a real web browser." This milestone has nothing to do with the language model at all. It's the plumbing that lets any caller, human or AI, drive a real Chromium browser through a fixed set of simple actions (navigate, click, type, read text, wait, handle a popup, etc).

This was built and fully tested **before** any model was wired up to it (that happens in Milestone 3), on purpose. The idea is to prove this layer works correctly in isolation first, so that when the agent loop is wired up next, any bug that shows up can be assumed to be in the agent/model side, not silently caused by a shaky browser layer underneath it.

## Background: what is Playwright, and why an HTTP layer on top of it

[Playwright](https://playwright.dev) is a library that lets a Python program control a real web browser (Chromium, in this project's case) the way a human would: open a page, find an element, click it, type into a field, read the text on the screen. It can run "headless," meaning the browser runs with no visible window, which is normal for automated testing and for anything running inside a server or a Docker container with no display.

The project's overall architecture (see the main README) plans to run two separate Docker containers: an **agent** container (does the thinking: talks to Ollama, decides what to do next) and a **browser** container (has an actual Chromium browser installed and does the clicking). These containers don't share memory or a filesystem, so the agent container cannot just import Playwright and drive the browser directly, because the browser doesn't exist inside the agent's container at all. Instead, the browser container exposes its capabilities over a plain HTTP API (using [FastAPI](https://fastapi.tiangolo.com), a Python framework for building HTTP APIs), and the agent container will call that API over the network, the same way it would call any other web service. This milestone builds that HTTP API.

## The two files

### `browser/actions.py`: the actual browser logic

This file defines `BrowserSession`, a class that holds exactly one Chromium browser tab open for as long as the process is running (not opening and closing a new browser for every single action, which would be slow and would lose things like login cookies between steps). It has one method for each of the 8 browser-facing tools from the project's tool schema:

| Method | What it does | What it returns on success |
|---|---|---|
| `navigate(url)` | Goes to a URL | Page title, URL, headings, and visible clickable element text |
| `click(selector=None, text=None)` | Clicks an element found either by a CSS selector or by its visible text | Same summary as `navigate` |
| `type_text(selector, text)` | Types text into a matching input field | Just a success flag |
| `extract_text(selector)` | Reads the text content of a matching element | The text itself |
| `screenshot()` | Takes a PNG screenshot of the current page | The image, base64-encoded |
| `wait_for(selector, timeout_ms)` | Waits for an element to become visible, for pages where content loads late (e.g. via JavaScript after a delay) | Success or a timeout error |
| `handle_dialog(action)` | Decides how the *next* browser popup (a JS `alert()` or `confirm()`) should be answered | Success flag |
| `get_page_state()` | A cheap, minimal snapshot: current URL, title, and headings | Just those three things |

**Every single one of these methods returns a plain Python dictionary with a `"success"` key, instead of raising a Python exception when something goes wrong** (like a missing element or a page that fails to load). This is a deliberate design choice, not an oversight. The whole point of the project's "self-correction" idea (see the Milestone 3 doc) is that when an action fails, the agent should get that failure back as information it can read and reason about, and try something different next. If a failed click instead crashed the Python program with an unhandled exception, the entire agent loop would die on the very first mistake, which defeats the purpose of an agent that's supposed to recover from mistakes on its own. So instead of `{"success": False, "error": "..."}`, a raw Playwright error is caught and turned into that shape:

```python
async def click(self, selector: str | None = None, text: str | None = None) -> dict:
    if selector:
        locator = self.page.locator(selector)
    elif text:
        locator = self.page.get_by_text(text, exact=False)
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
```

### A tricky detail: JavaScript popup dialogs

Some web pages use the browser's built-in `alert()` or `confirm()` popups (the "OK / Cancel" boxes). These are awkward to automate because Playwright's default behavior is to **automatically dismiss them the instant they appear**, unless something has already told it in advance what to do. That "something" has to be registered *before* the popup ever fires, because by the time your code notices a popup happened, Playwright has already auto-dismissed it.

The fix: when `BrowserSession.start()` runs (once, when the browser first launches), it registers a permanent listener:

```python
async def start(self) -> None:
    self._playwright = await async_playwright().start()
    self._browser = await self._playwright.chromium.launch()
    self._page = await self._browser.new_page()
    self._page.on("dialog", self._on_dialog)
```

Then `handle_dialog(action)` doesn't try to interact with a popup directly at all, since none may exist yet. It just sets a flag (`self._next_dialog_action`) recording whether the *next* popup that appears, whenever that turns out to be, should be accepted or dismissed. When a popup does eventually appear, the always-on listener checks that flag and acts accordingly:

```python
async def _on_dialog(self, dialog: Dialog) -> None:
    if self._next_dialog_action == "accept":
        await dialog.accept()
    else:
        await dialog.dismiss()
```

This was verified against a small test page with a button that triggers `window.confirm()`, checking both the "accept" and "dismiss" outcomes actually happen and get recorded correctly.

### Why `_summary()` and `get_page_state()` are two different functions, on purpose

It might look redundant to have two functions that both describe "what does the page look like right now." They're kept deliberately different sizes for different jobs, matching the project's tool schema:

- `_summary()` (used after `navigate` and `click`, the two actions most likely to change what's on screen) returns title, URL, headings, *and* the visible text of clickable elements (buttons, links), because after moving to a new page or clicking something, the agent needs enough detail to decide what to do next.
- `get_page_state()` (a separate, standalone tool) is meant as a **cheap re-orientation check after something has gone wrong**, so it intentionally leaves out the clickable-elements list and returns only URL, title, and headings, the minimum needed to answer "wait, where am I right now."

The project's own internal notes are explicit that these two should not be casually merged into one shared function later without re-checking why they're different sizes.

### `browser/server.py`: the thin HTTP wrapper

This file is much smaller. It uses FastAPI to expose one HTTP endpoint per `BrowserSession` method (`POST /navigate`, `POST /click`, `GET /get_page_state`, and so on), using FastAPI's `lifespan` feature to start the browser once when the web server process starts up, and cleanly close it when the server shuts down, rather than opening a new browser per request. Each endpoint is a couple of lines: parse the incoming JSON request body, call the matching `BrowserSession` method, and return whatever dictionary it produced directly as the HTTP response.

## How this was verified

**Automated tests** (`tests/test_browser_actions.py`, 15 tests) run directly against `BrowserSession`, not through the HTTP layer, and against a small local static HTML file (`tests/fixtures/sample_page.html`) instead of a real website. This makes the whole suite run in about 13 seconds with no dependency on the internet or on some external site staying online and unchanged. The tests cover both the success and the failure path for every method (for example: clicking something that exists, and separately, clicking a selector that doesn't exist and checking the error dict comes back correctly instead of an exception). One test uses an element that only appears after a delay (via `setTimeout` in the fixture page's own JavaScript) specifically to prove `wait_for` genuinely waits rather than just checking once immediately. Both dialog outcomes (accept and dismiss) are tested against a fixture button that calls `window.confirm()` and records what happened.

This also required a small CI change: the pipeline's `test` job previously only ran `pip install playwright`, which installs the Python library but not an actual browser binary. A `playwright install --with-deps chromium` step had to be added so a real Chromium binary exists for these tests to launch against in CI, not just locally.

**Manual verification beyond the automated tests**: the FastAPI server was also run locally with `uvicorn browser.server:app`, and every single endpoint was exercised by hand with `curl`. Separately, the real Docker image for this service was built and started with `docker compose up -d browser`, and its endpoints were hit again, this time over the actual container network and against a real external site (`https://example.com`), not the local test fixture, to confirm the whole thing works the same way once it's actually inside a container, not just when run directly on the laptop.

## What's next

Milestone 3 is where a real language model gets wired up to actually call these tools for the first time, instead of a human calling them by hand with `curl`. See `docs/milestones/03-react-loop.md`.