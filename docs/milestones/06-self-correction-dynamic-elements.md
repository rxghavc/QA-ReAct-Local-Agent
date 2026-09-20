# Milestone 6: self-correction and dynamic elements

## What this milestone was supposed to build, according to the plan

The original project plan describes a specific mechanism for self-correction: "if the same action fails 2-3 times in a row, force a re-plan step." The idea is that a model might get stuck retrying an identical failing action over and over (the same bad selector, the same bad click), and the fix is to notice that pattern in code and interrupt it with a forceful nudge telling the model to try something different.

This milestone also planned to add "Tier 3" tasks: pages with dynamic loading (content that only appears after a delay), JavaScript dialogs (`alert`/`confirm` popups), and iframes (a page embedded inside another page), specifically because these are the kinds of pages that are more likely to trip up an agent that can't adapt.

## What the real data from Milestone 5 actually showed

Before writing any new code, it's worth re-reading exactly what went wrong in Milestone 5's benchmark run (see that milestone's doc for full detail), because it doesn't quite match the failure mode the plan's mechanism was designed for:

- `task_03_saucedemo_add_to_cart`: the model clicked the wrong element (`.inventory_item`, a product's info panel, not its "Add to cart" button) **once**, that click "succeeded" (no error), and the model immediately called `report_done`, falsely claiming success.
- `task_04_saucedemo_checkout`: the model tried a selector that matched nothing (`.btn_primary:first-child`) **once**, it timed out, and the model immediately called `report_blocked`, correctly reporting failure this time, but without trying any alternative first.

Neither of these is "the model retried the same failing action repeatedly." In both cases, the model only tried **one** thing before either giving up or claiming false success. The plan's stuck-detection mechanism, as literally described, requires the *same* action to fail two or three times before it would even trigger, and neither of these failures would have tripped it, because there was no repetition at all. This is exactly the kind of thing worth being honest about rather than building the originally-planned mechanism and declaring victory regardless of whether it actually addresses the real problem: the plan's assumption about *how* the model gets stuck didn't match what was actually observed once real data existed.

## What was actually built, and why it's three different fixes, not one

### 1. The originally-planned stuck-detection mechanism, built anyway

Even though it wasn't what caused Milestone 5's specific failures, repeating an identical failing action is still a real, plausible failure mode worth guarding against (for example, in a genuinely flaky or slow-loading page, a `wait_for` might reasonably fail once and be worth retrying with a longer timeout, but failing the exact same way three times in a row is a sign something structural is wrong, not bad luck). So `agent/loop.py` now tracks the most recent failed tool call and how many times in a row it's failed with the exact same name and arguments. On the second consecutive identical failure, a message is injected into the conversation, in the model's own words this time, not just a data blob:

```python
def _stuck_nudge(call: dict) -> dict:
    return {
        "role": "user",
        "content": (
            f"You've now called {call['name']} with the exact same arguments "
            f"({json.dumps(call['arguments'])}) {STUCK_THRESHOLD} times in a row "
            "and it failed the same way every time. Repeating it again is not "
            "going to work. Try a genuinely different approach: a different "
            "selector, matching by visible text instead of a CSS selector, or "
            "calling get_page_state to re-orient yourself first."
        ),
    }
```

This is tested directly (`tests/test_agent_loop.py`): a scenario where the same call fails four times in a row confirms exactly two nudges fire (after failure 2 and after failure 4, since the counter resets after each nudge), and separate scenarios confirm a single failure, or failures that alternate between two different calls, never trigger a nudge at all.

### 2. Stronger, more directive prompting, which is what actually fixed the two real failures

Since the real problem was "gives up or hallucinates after one attempt," not "loops on the same mistake," the actual fix needed to happen earlier: change what the model is told to do *before* it even gets to a second attempt. Three new rules were added to `agent/prompts.py`'s system prompt:

- If a tool call fails, don't repeat the exact same action. Prefer matching by visible text over a CSS selector that just failed.
- A JavaScript dialog fires the instant the action that triggers it happens, so `handle_dialog` has to be called *before* that action, not after (this rule exists specifically for the new `task_07_js_confirm_dialog` task, described below).
- A tool call reporting success doesn't guarantee the task actually progressed (clicking the wrong element still "succeeds" as a click). Before calling `report_done`, check for real evidence the expected thing happened, don't just assume it from a non-erroring click.

This is a deliberately different kind of fix than the stuck-detection mechanism: it's not code watching for a pattern and interrupting the model, it's changing what the model is told up front, so the bad pattern (give up or hallucinate after one try) hopefully doesn't start in the first place.

### 3. New Tier 3 tasks, and one deliberately skipped

Two new tasks were added, each chosen because it specifically exercises one of the new prompt rules, and each verified directly against the real page with a throwaway Playwright script before being written into a task file (the same practice used for the saucedemo tasks in Milestone 5), rather than guessed from memory:

- **`task_06_dynamic_loading`** (`the-internet.herokuapp.com/dynamic_loading/1`): clicking "Start" begins a loading spinner, and a `#finish` element that already exists in the page's HTML (confirmed directly: `count()` returns 1 even before clicking Start) stays hidden until the spinner finishes a few seconds later. This tests whether the model actually waits for the element to become visible (using `wait_for`) rather than reading it too early or giving up.
- **`task_07_js_confirm_dialog`** (`the-internet.herokuapp.com/javascript_alerts`): clicking "Click for JS Confirm" triggers a real `window.confirm()` popup. This directly tests the new "call `handle_dialog` before, not after" rule, since Playwright's dialog handling (registered once at browser startup, see Milestone 2) only works if the *next* dialog's outcome was already decided before it fires.

**Iframes, the third Tier 3 category from the plan, were deliberately left out of this milestone**, and it's worth being specific about why: `BrowserSession`'s Playwright calls all use `self.page.locator(selector)`, which only searches the page's main frame. An element inside an `<iframe>` is invisible to every single one of this project's tools right now, `click`, `type_text`, `extract_text`, all of it, there's no `text` or `selector` that would ever find it. This isn't a self-correction problem a smarter prompt or a stuck-detection nudge can work around, it's a missing capability in the browser tool layer itself (`page.frame_locator(...)` would be needed). Rather than quietly build a narrow, iframe-specific workaround to hit a task-count target, this is named here as real, scoped-out future work.

## The first live result: 6/7 passed, and a brand-new failure appeared

With both the stuck-detection code and the new prompt rules in place, the full seven-task suite (five from Milestone 5 plus the two new Tier 3 tasks) was run for real:

```
6/7 tasks passed
6/7 self-reports matched the real outcome

  [FAIL] task_01_the_internet_login (self-report: done, steps: 5, 30.6s)
  [PASS] task_02_saucedemo_login
  [PASS] task_03_saucedemo_add_to_cart
  [PASS] task_04_saucedemo_checkout
  [PASS] task_05_saucedemo_logout
  [PASS] task_06_dynamic_loading
  [PASS] task_07_js_confirm_dialog
```

The good news first: both of Milestone 5's actual failures, `task_03` and `task_04`, now passed, and both brand-new Tier 3 tasks passed on the first try. The prompt changes did what they were meant to do.

The bad news: `task_01_the_internet_login`, which had passed reliably in every single earlier milestone, now failed, and it failed the exact same way as Milestone 5's `task_03`: the model confidently called `report_done` when the login had never actually happened.

## Finding the real root cause, not guessing at it

Reading the trace showed the model called `click(text="Login")` this time (previously it had used a CSS selector). The click reported `success: true`, but the page afterward looked completely unchanged, still on the login page, same headings, same clickable elements listed, exactly as before the click. Something was clicked, but it did nothing.

Rather than guess, this was checked directly with a small throwaway script, listing every element on that exact live page that `get_by_text("Login", exact=False)` (the exact call `BrowserSession.click()` was making) would match:

```
matches for get_by_text('Login', exact=False): 2
  [0] <H2> 'Login Page'
  [1] <I> ' Login'
```

There it is: the page has an `<h2>Login Page</h2>` heading, and the word "Login" is a substring of "Login Page." Since that heading appears in the HTML before the actual submit button's icon element, and `BrowserSession.click()` always took `.first` off whatever the text search returned, it clicked the heading. Clicking a heading doesn't raise any error, so the click "succeeded," and, despite the brand-new prompt rule that specifically says to verify success before calling `report_done`, the model didn't call `extract_text` or `get_page_state` to check. It just assumed the click had worked and reported done.

This is worth sitting with for a moment: **the exact fix that was added to solve Milestone 5's two failures (prefer text matching over a bad selector) is what directly caused this new failure**, on a page that happens to have a heading whose text overlaps the target button's label. And the other new prompt rule, "verify before declaring done," which was specifically written to prevent exactly this class of hallucinated success, didn't stop it, because telling a model to do something in a prompt doesn't guarantee it reliably will. Prompting can shift behavior; it doesn't give hard guarantees the way a code-level check does.

## The decision: this is a tool-layer bug, not something to leave for the model to work around

There's a real design question here: should this be treated the way the Milestone 3 `#login`-is-a-form-id issue was, as a self-correction gap to leave alone so a future retry mechanism has something real to solve? The judgment call made here was no, and for a specific reason: `click(text="Login")` is supposed to mean "click the button or link labeled Login." A plain, page-wide, substring text search doesn't actually implement that intent correctly, on *any* page with a heading, label, or paragraph that happens to contain the target word, this exact bug could recur, regardless of how good the model's own retry strategy is. This isn't a case of the model needing to be smarter about recovering from a bad situation, it's a case of one of its tools doing something other than what it's documented to do. That's a straightforward bug fix, not scope creep into "hardcoding around self-correction."

The fix, in `BrowserSession.click()` (`browser/actions.py`): when matching by `text`, first search only inside actually-clickable elements (`button, a, input[type=submit], input[type=button], [role=button]`) for that text, and only fall back to the original unrestricted page-wide search if nothing clickable matches at all:

```python
elif text:
    interactive = self.page.locator(INTERACTIVE_SELECTOR).filter(has_text=text)
    locator = (
        interactive
        if await interactive.count() > 0
        else self.page.get_by_text(text, exact=False)
    )
```

A permanent regression fixture was added to `tests/fixtures/sample_page.html`: a heading (`<h2>Login Page</h2>`) immediately followed by a same-labeled button (`<button>Login</button>`), reproducing the exact ambiguity found on the live site, with a test asserting the button, not the heading, gets clicked.

## The final result

With the browser-layer fix in place, the full seven-task suite was run one more time:

```
7/7 tasks passed
7/7 self-reports matched the real outcome
```

Every task passed, and every one of the model's own done/blocked claims matched the programmatic scorer's verdict. But it's worth being precise about what produced that result: not one clever mechanism, but three different fixes operating at three different layers (loop-level stuck detection, prompt-level guidance, and a browser-layer bug fix), only two of which were actually planned in advance, found by actually running the thing against live data at each step rather than reasoning about it in the abstract.

## What's next

Milestone 7 adds `llama3.2:3b` as a cheap routing checkpoint alongside the `qwen2.5-coder:14b` planner, and measures its actual effect on latency and step count against this now-passing seven-task suite, which finally gives that comparison a stable, reliable baseline to measure against.