# Milestone 5: building the actual benchmark

## What this milestone was actually building

Every milestone so far has proven the agent works using a single, human-chosen, hardcoded task, and a human reading the printed trace to decide whether it actually worked. That doesn't scale, and it isn't honest measurement: one anecdote (see Milestone 4's finding that the same model, same task, gave a different, better answer on a second run) tells you almost nothing about how reliable the agent actually is. This milestone replaces "a human reads a trace" with an actual, repeatable benchmark: a set of tasks defined as data (not code), a way to check automatically whether each one really succeeded, and a permanent log of every run.

This is also the first milestone where the model's own `report_done` / `report_blocked` claim gets checked against something else, for real, in code, rather than just discussed as a design principle. Milestones 1 through 4 kept saying "the model's self-report should never be trusted alone," but nothing had actually verified that in an automated way until now.

## Background: why "the model says it worked" isn't good enough, concretely

Language models can be confidently wrong. A model that clicks the wrong element on a page might see nothing obviously go wrong (no error message, no crash) and simply report success, because from its point of view, it did what it intended to do. The only way to know for certain whether a task actually succeeded is to check the real, final state of the browser against something objective: does the URL match what a successful task would produce, does a specific element on the page contain the text you'd expect to see only after success. That's what a **scorer** is: a small, deterministic function that looks at real evidence (not at what the model claims) and returns true or false.

This project also tracks something extra worth explaining: **self-report accuracy**. Separately from "did the task pass," this measures "did the model's own claim about whether it succeeded match reality." A model can fail a task in two very different ways: it can honestly say "I couldn't do this" (a correct, if disappointing, self-report), or it can falsely claim success when it didn't actually succeed (a much worse failure, because nothing downstream would know to double-check it). Both failures still count as a failed task, but only the second one is also a self-report failure, and telling those apart matters for understanding how much you can trust the model's own claims in general.

## The pieces that were built

### The task file format (`benchmark/tasks/*.yaml`)

Each task is one small YAML file. Here's `task_04_saucedemo_checkout.yaml` (deliberately kept close to the exact example already written into the original project plan, almost word for word):

```yaml
- id: task_04_saucedemo_checkout
  instruction: >
    Go to https://www.saucedemo.com/, log in with username 'standard_user'
    and password 'secret_sauce', add the first product on the page to the
    cart, go to the cart, check out with first name 'Test', last name
    'User', and postal code '12345', then report done once the order is
    complete.
  success_check:
    type: dom_text_contains
    selector: ".complete-header"
    expected: "Thank you for your order"
  max_steps: 15
  timeout_seconds: 120
```

`instruction` is the plain-English task handed to the model exactly as-is, no hidden hints about which selectors to use. `success_check` is the objective, programmatic pass condition. `max_steps` overrides the agent loop's default step budget per task (a simple login needs far fewer steps than a full checkout).

### The scorer (`benchmark/runner.py`'s `score_task`)

Three check types were implemented, covering the two kinds of evidence the original plan specifically called out ("DOM text match, URL match"):

- **`url_contains`**: does the final page's URL contain a given substring (used for the login tasks, where reaching a specific new URL is proof enough that login worked).
- **`url_equals`**: does the final URL match exactly (used for the logout task, where "back at the exact starting URL" is the actual success condition).
- **`dom_text_contains`**: does a specific element (found by a CSS selector) contain a given piece of text (used for the checkout task, checking for saucedemo's own "Thank you for your order!" confirmation message, and for the add-to-cart task, checking the cart icon's item-count badge).

`score_task(task, final_browser_state)` is a small, pure function: given a task's `success_check` and a dictionary describing the page's actual final state, it returns `True` or `False`, no browser calls of its own. That makes it trivial to unit test with made-up inputs, without needing a live browser at all, which is exactly how it's tested in `tests/test_benchmark.py`.

Getting that `final_browser_state` dictionary in the first place is a separate step (`_fetch_final_state`), which happens right after the agent loop ends: it asks the still-open, still-on-the-final-page browser session for its current URL/title/headings (the same `get_page_state` tool the agent itself can call), and, if the task's check needs specific text, also asks for that element's text (the same `extract_text` tool). This matters: it's checking the *exact* page the agent left behind when it stopped, not a fresh reload, which is the only way to get an honest picture of what state the agent's actions actually left the browser in.

### The logger

Every single run, whether it passes or fails, gets written to `logs/<task_id>_<timestamp>.json`, containing the pass/fail verdict, the model's self-report, whether they agreed, how many steps it took, how long it took, the final browser state, and the entire step-by-step trace. `benchmark/report.py` reads every log file in `logs/` and rolls them up into an overall pass rate, self-report accuracy, and average step count. Log files themselves are gitignored (only `.gitkeep` is tracked), since they're a growing pile of run artifacts, not source code, but the code that produces and reads them is exactly what makes the project's "regression tracking" goal (re-run the suite over time and watch the trend) possible later.

### A limitation that was checked directly instead of assumed

All five tasks in one call to `run_suite()` run against the same single, persistent browser session (the same design from Milestone 2: one `BrowserSession` kept open for the life of the process, not a fresh browser per task). That means task 2's browser still has whatever cookies and page state task 1 left behind, and so on down the list. This is a real risk for a benchmark suite specifically, since tasks are supposed to be independent, a later task could accidentally pass or fail because of something an earlier task did, not because of its own merits.

This was checked directly rather than assumed away: a small throwaway script logged into saucedemo, then navigated straight back to the root URL without logging out, to see whether the site would just skip the login form for an already-authenticated session. It didn't, saucedemo always renders its login form at `/` regardless of any existing session, so this particular set of five tasks is safe. But this is a real, named simplification, not a guarantee that would hold for every future task. A task suite that needed true isolation (a genuinely fresh browser, fresh cookies, for every single task) would need a new capability that doesn't exist yet, and this is worth remembering before adding tasks that depend on *not* having any prior state.

## Running the suite for real

With the browser service and Ollama both running, `python -m benchmark.runner` loads all five tasks, runs each one through the real agent loop, scores it, prints a summary, and writes five new log files. The first real run:

```
3/5 tasks passed
4/5 self-reports matched the real outcome

  [PASS] task_01_the_internet_login (self-report: done, steps: 5, 27.9s)
  [PASS] task_02_saucedemo_login (self-report: done, steps: 5, 21.6s)
  [FAIL] task_03_saucedemo_add_to_cart (self-report: done, steps: 6, 30.6s)
  [FAIL] task_04_saucedemo_checkout (self-report: blocked, steps: 6, 34.0s)
  [PASS] task_05_saucedemo_logout (self-report: done, steps: 7, 34.1s)
```

## The two failures, in detail, and why they're a good result for this milestone

The point of building a scorer is to catch problems a human skimming a trace might miss or might not have thought to check for. Both failures here are real, and both are informative in different ways.

### `task_03_saucedemo_add_to_cart`: a hallucinated success, caught

The trace showed: navigate, type username, type password, click `#login-button` (all fine), then a `click` with `selector: ".inventory_item"`, which matches the product's whole info panel (its name, description, and price), not its "Add to cart" button. Clicking that panel doesn't raise any error, Playwright just clicks it and reports success, so from the model's point of view, its click "worked." It then called `report_done`, claiming the product had been added to the cart.

The scorer's `dom_text_contains` check on `.shopping_cart_badge` found no such badge on the page at all (the check never even got real text back), because nothing was ever actually added to the cart. This is exactly the false-positive scenario the plan's self-report-accuracy metric is designed to surface: the model was confidently, cleanly wrong, with no error anywhere in its own trace to tip it off. This is the one case out of five where the model's self-report and the real outcome disagreed.

### `task_04_saucedemo_checkout`: the same button, a different wrong guess, caught honestly

On this task, the model tried a different selector for the same "Add to cart" button: `.btn_primary:first-child`. This selector requires the button to literally be the first child element of its parent container, which it isn't (the button sits after the product's name, description, and price elements inside that container), so nothing matched, and the click timed out after 5 seconds. This time, the model correctly recognized the failure and called `report_blocked` with an honest reason, rather than claiming success it hadn't earned. That's a correct self-report about a genuine failure, unlike the previous task.

### The pattern worth naming

Two different tasks, two different runs, two different wrong selector guesses for the exact same physical button on the exact same page (`.inventory_item` and `.btn_primary:first-child`), neither of which actually targets the real "Add to cart" button. Neither run tried the simpler, more robust option of matching the button by its visible text ("Add to cart"), the same `text` argument the `click` tool already supports, and the same kind of fallback that was already identified as missing back in the Milestone 3 finding about the `#login` selector. This is no longer a one-off anecdote, it's now a reproducible, benchmarked weak spot: **this model has no reliable strategy for picking a CSS selector on this specific page, and doesn't fall back to matching by visible text on its own.** That is precisely the class of problem Milestone 6 (self-correction and dynamic elements, including the plan's "if the same action fails 2-3 times in a row, force a re-plan step" idea) exists to fix, and now there's a concrete, repeatable failing task to measure any fix against, instead of just a description of the problem.

## What's next

Milestone 6 builds the actual retry/re-plan logic this benchmark run just proved is necessary, plus the Tier 3 task category (dynamic loading, JS dialogs, iframes) that specifically exercises it.