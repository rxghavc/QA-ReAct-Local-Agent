# How to run the agent

This answers two things that aren't obvious from the code alone: what
you can actually run today, and how to watch the agent work rather than just
read its trace log afterward.

## Is this CLI-based, or can I watch the agent work?

Both, but not at the same time without a flag.

**Today there is no web UI.** `agent/api.py` is a deliberate, scoped-out stub
(both endpoints `raise NotImplementedError`); the project's own decision,
confirmed 17 Sept 2026, is a recorded demo video, not a live interactive UI.
Everything below is CLI-only.

**The browser itself runs headless by default**, which is correct for the
benchmark suite (fast, no display needed, works the same in Docker and CI)
but means there is nothing to watch. `browser/actions.py`'s `BrowserSession`
now reads a `BROWSER_HEADLESS` environment variable:

```bash
BROWSER_HEADLESS=false uvicorn browser.server:app --port 8001
```

Set to anything other than `false` (including unset) it stays headless. With
it set, a real Chromium window opens and you can watch every `navigate`,
`click`, and `type_text` call happen on screen in real time, driven by
whatever task you point the agent at.

**This only works running the browser service locally, not inside the Docker
container.** The container has no display to render a window on; making that
work would mean adding Xvfb + a VNC server + noVNC to `browser/Dockerfile`,
which is real infrastructure work with no payoff for a recorded demo, so it's
deliberately not done. Run headed locally for anything you want to watch or
film; use Docker (headless, as already set up) for the benchmark runs whose
numbers go in the README.

## Running things

All commands assume `ollama serve` is running with `qwen2.5-coder:14b`
pulled, and are run from the repo root with the dev virtualenv active.

### 1. Start the browser service

Headless, for a benchmark run:

```bash
docker compose up -d browser
# or, without Docker:
uvicorn browser.server:app --port 8001
```

Headed, for watching or filming:

```bash
BROWSER_HEADLESS=false uvicorn browser.server:app --port 8001
```

### 2. Run one ad-hoc task

`agent/loop.py` takes an optional task string and prints the full trace as
JSON:

```bash
python -m agent.loop "Go to https://www.saucedemo.com/, log in with \
username 'standard_user' and password 'secret_sauce', add the first \
product to the cart, go to the cart, check out with first name 'Test', \
last name 'User', and postal code '12345', then report done once the \
order is complete." --max-steps 15
```

Run with no argument and it falls back to the Milestone 3 hardcoded login
task. This is the tool for filming: point it at whatever task you want on
screen, independent of the benchmark suite's own YAML files.

### 3. Run the benchmark suite

```bash
python -m benchmark.runner --repeat 3   # 3 passes; a single pass is not a measurement
python -m benchmark.report --last 36    # aggregates the last N logged runs
```

Checks all three benchmark sites are reachable first (skips a task rather
than scoring an outage as a failure), and re-reads every task YAML at the
start of each pass, so don't edit a task file mid-run.

## What's still CLI-only, by design

- No live dashboard or run-trigger API. `agent/api.py` stays an
  unimplemented stub; see the README's Status section and
  `docs/milestones/` for why this was scoped out rather than left unnoticed.
- No headed mode inside Docker. Deliberate, see above.