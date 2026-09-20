# Milestone 3: Wiring up the actual agent loop

## What this milestone was actually building

Milestones 1 and 2 built the two halves of this project separately and proved each one works on its own: Milestone 1 proved a local model can reliably say "call this tool with these arguments" (using a fallback JSON parser, since native tool-calling didn't work, see that doc for details). Milestone 2 built a real, tested browser control layer that anything can call over HTTP to actually drive a Chromium browser.

Milestone 3 connects those two things for the first time. Before this milestone, `agent/loop.py`, `agent/ollama_client.py`, `agent/tools.py`, and `agent/prompts.py` were all empty stub files that just raised `NotImplementedError`. This milestone made all four of them real, and then actually ran one hardcoded task (logging into a demo website) with a live model driving a live browser, end to end, to prove the whole chain works together, not just in theory.

## Background: what is a "ReAct loop"

**ReAct** stands for **Reason + Act**, and it's a common pattern for building AI agents: repeat a cycle of (1) the model reasons about what to do next given everything that's happened so far, (2) the program actually performs whatever action the model chose, (3) the result of that action ("observation") gets added to the conversation so the model can see what happened, and the cycle repeats. This keeps going until the model says it's done, says it's stuck, or a safety limit (`max_steps`) is hit so a broken task can't loop forever.

## The four files, what each one does, and why

### `agent/ollama_client.py`: talking to the model

This is where the fallback-parsing approach proven in the Milestone 1 spike actually gets used for real, generalized to work with any set of tools instead of the spike's three toy ones. `ollama_chat()` is a thin wrapper that sends the conversation so far to Ollama's `/api/chat` endpoint and returns the model's reply. `extract_tool_call()` is the parser: check Ollama's native `tool_calls` field first (still checked, just in case, even though the spike showed this model doesn't use it), and if that's empty, look for a JSON object in the plain text reply instead, same `json.JSONDecoder().raw_decode()` approach as the spike, for the same reason (the model sometimes writes several steps' worth of JSON back to back instead of one at a time).

### `agent/prompts.py`: telling the model what it can do

`system_prompt()` builds the instructions sent to the model at the very start of every task. It lists every available tool by name with a short description, and spells out, in plain words, exactly what shape of answer is expected: a single JSON object like `{"name": "<tool_name>", "arguments": {...}}`, with no extra commentary. This exists because, per the Milestone 1 finding, this model cannot be trusted to reliably use Ollama's official `tools` mechanism on its own, so the instructions have to say directly, in the prompt text itself, what format to reply in.

### `agent/tools.py`: what the model is allowed to do, and how those requests actually happen

This file has two jobs. First, `TOOLS` is the full list of all 10 tools from the project's plan (the 8 browser actions from Milestone 2, plus two new ones: `report_done` and `report_blocked`, which don't touch the browser at all, they just signal that the task is over), each with a JSON schema describing its arguments, in the format Ollama (and the prompt) expect.

Second, `execute_tool()` is the dispatcher: given a parsed tool call like `{"name": "click", "arguments": {"text": "Login"}}`, it looks up which HTTP endpoint on the Milestone 2 browser service that corresponds to (for example, `click` maps to `POST /click`), makes the actual HTTP request, and returns whatever the browser service replied with. Matching the design principle from Milestone 2, if the browser service itself is unreachable (for example, its container isn't running), that comes back as a `{"success": False, "error": "..."}` dictionary too, not a crash, so a network problem is just another kind of failure the model can see and react to.

### `agent/loop.py`: the actual orchestration

This is the real ReAct loop:

```python
def run_task(task: str, max_steps: int = 15) -> dict:
    messages = [
        {"role": "system", "content": system_prompt(task, TOOLS)},
        {"role": "user", "content": task},
    ]
    trace: list[dict] = []

    for step in range(max_steps):
        message = ollama_chat(PLANNER_MODEL, messages, tools=TOOLS)
        messages.append(message)
        call = extract_tool_call(message, _TOOL_NAMES)

        if call is None:
            return {"outcome": "stuck", ...}

        if call["name"] in TERMINAL_TOOLS:  # report_done or report_blocked
            return {"outcome": "done" or "blocked", ...}

        result = execute_tool(call)
        messages.append({"role": "tool", "content": json.dumps(result)})

    return {"outcome": "max_steps", ...}
```

Every run of a task ends in exactly one of four outcomes, and every one of them is a normal, expected result, not a crash:

- **`done`**: the model called `report_done`, claiming the task is finished.
- **`blocked`**: the model called `report_blocked`, claiming the task can't be completed.
- **`stuck`**: the model's reply couldn't be parsed into any tool call at all.
- **`max_steps`**: the step budget ran out before the model called either terminal tool.

Note that `report_done` and `report_blocked` never touch `execute_tool()` or the browser at all, they're purely a signal that ends the Python loop.

## Why the tests don't need a live model or a live browser

40 (later 41) automated tests were written across three files, and every single one of them runs completely offline, with no Ollama and no browser container needed. This is done with `monkeypatch` (a pytest feature for temporarily replacing a function with a fake one during a test): `tests/test_ollama_client.py` feeds hand-written fake model replies straight into `extract_tool_call()` to check the parsing logic in isolation; `tests/test_tools.py` replaces the underlying `httpx.get`/`httpx.post` calls with fakes that record what URL and JSON body they were called with, instead of actually hitting a network address; `tests/test_agent_loop.py` replaces both `ollama_chat` and `execute_tool` with scripted fake responses to check that `run_task()` reaches the right outcome (`done`, `blocked`, `stuck`, `max_steps`) for each of the four scenarios. This is why CI can run this suite on every single change in a few seconds, without needing a GPU or an actual browser installed.

## Running it for real: two findings from the very first live attempt

Once the code passed its offline tests, the plan called for actually running it against the real model and the real browser service, using one hardcoded task: log into `https://the-internet.herokuapp.com/login` with a known username and password, and call `report_done` once a success message appears. This immediately surfaced two real problems that the offline, mocked tests had no way of catching, because they only exist when a live model is actually involved.

### Finding 1: the model wrapped its answer in a Markdown code fence

The very first live run came back as `"stuck"` on the first step. The model's actual reply was:

````
```json
{
  "name": "navigate",
  "arguments": {
    "url": "https://the-internet.herokuapp.com/login"
  }
}
```
````

This is perfectly valid, sensible JSON, a person reading it would have no trouble understanding it, but it's wrapped in a Markdown "code fence" (the ` ```json ` and ` ``` ` lines), which the Milestone 1 spike's parser never had to deal with because the spike never happened to produce that shape. The fix was a small addition to `extract_tool_call()`: after checking for the `<tool_call>` tag wrapper, also check for and strip a code fence, before attempting to parse the remaining text as JSON. A regression test for this exact case was added at the same time, so it can never silently regress.

The broader lesson: a parser proven against one specific spike script is not automatically proven against every way a live model might phrase its answer. Defensive parsing has to keep being revisited as the model gets used in new ways.

### Finding 2: the loop finished cleanly, but the actual task failed, for a subtle reason

After fixing the code-fence issue, the loop ran to completion without crashing or getting stuck. Here is exactly what happened, step by step:

1. `navigate` to the login page. Succeeded.
2. `type_text` into `#username` with `"tomsmith"`. Succeeded.
3. `type_text` into `#password` with `"SuperSecretPassword!"`. Succeeded.
4. `click` with **both** `selector: "#login"` and `text: "Login"` given at the same time.
5. `wait_for` on `#flash` (the selector for the page's success/error message banner). This **timed out**.
6. The model called `report_blocked`, with the reason "the login confirmation message did not appear within the timeout period."

Why did step 4 not actually submit the login form? Two things combined:

- `BrowserSession.click()` (from Milestone 2) checks `selector` first and only falls back to `text` if no selector was given at all. Since the model supplied both, `text` was silently ignored.
- On this particular page, `#login` is not the id of the submit button (the button has no id at all). It's the id of the surrounding `<form>` element. Clicking a `<form>` element doesn't cause an error, Playwright happily reports success, but it also doesn't submit anything, because a `<form>` isn't the button.

So the click "succeeded" (`success: true` came back), but nothing meaningful happened on the page. The subsequent `wait_for` correctly noticed nothing changed and timed out, and the model, seeing that timeout, correctly decided the task hadn't worked and reported it as blocked rather than falsely claiming success. Its self-report was right in the sense that mattered (the login genuinely didn't happen), even though the specific reason it gave ("confirmation message didn't appear") was a step removed from the real root cause (it clicked the wrong element entirely).

This was deliberately **not** fixed by, say, special-casing `click()` to always try `text` as a fallback if `selector` fails. Per the project's own design principle, hardcoding around a specific failure like this defeats the purpose of the "self-correction" idea the whole project is trying to demonstrate: the interesting, hireable part of this project is teaching the *loop* to notice a repeated or unexpected failure and try a genuinely different approach on its own, which is exactly what Milestone 6 (self-correction and dynamic elements) is for. Fixing this one selector bug by hand here would remove the very case that milestone needs to solve for real.

## Why "the loop worked" and "the task passed" are different claims here

This project's design is explicit that the model's own `report_done` / `report_blocked` claim should never be treated as proof of anything by itself, a separate, independent, programmatic check (a scorer, built in Milestone 5) is supposed to be the real source of truth. This first live run is a concrete demonstration of exactly why that principle exists: the model's self-report here was directionally trustworthy (it correctly avoided claiming false success), which is a good sign, but the run still needed a human reading the trace to understand what actually went wrong and why. Milestone 3's bar was set as "the loop runs end to end against a real model and a real browser and produces a self-report that can be reasoned about," not "the hardcoded task passes," and by that bar, it succeeded.

## What's next

Milestone 4 took this same working loop and got it running fully inside Docker containers instead of as two processes on the laptop. See `docs/milestones/04-dockerize.md`.