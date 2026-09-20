# How to run the agent

This is the practical guide for running the project locally: the CLI workflow, the browser setup, and the benchmark commands that the repository expects.

## CLI-first workflow

There is no web UI today. `agent/api.py` is deliberately left as a stub, and the project’s working pattern is CLI-driven with an optional headed browser for demos or observation.

The browser service runs headless by default, which is the correct mode for benchmark runs and Docker-based execution. If you want to watch the browser in real time, start it with `BROWSER_HEADLESS=false`:

```bash
BROWSER_HEADLESS=false uvicorn browser.server:app --port 8001
```

This opens a real Chromium window and lets you watch actions such as navigation, clicks, and text entry happen on screen as the agent works.

## Local setup

All commands assume that Ollama is installed and running locally, and that you have pulled the same model family used in this project, `qwen2.5-coder:14b`, onto your own machine. This is not a hosted-service workflow; the model is expected to live on the machine running the agent.

This project was developed on a MacBook with an M4 chip and 24GB of unified memory, which is a comfortable local setup. A machine with around 16GB RAM can still work, but it will be noticeably slower and benchmark runs will take longer. If your hardware is weaker than that, expect slower inference and a more constrained experience.

### 1. Start the browser service

For a benchmark run, use headless mode:

```bash
docker compose up -d browser
# or, without Docker:
uvicorn browser.server:app --port 8001
```

For a headed run, start the browser service manually:

```bash
BROWSER_HEADLESS=false uvicorn browser.server:app --port 8001
```

### 2. Run one ad-hoc task

`agent/loop.py` accepts an optional task string and prints the full trace as JSON:

```bash
python -m agent.loop "Go to https://www.saucedemo.com/, log in with \
username 'standard_user' and password 'secret_sauce', add the first \
product to the cart, go to the cart, check out with first name 'Test', \
last name 'User', and postal code '12345', then report done once the \
order is complete." --max-steps 15
```

Running it with no argument falls back to the default task. This is the easiest way to test a specific flow without relying on the benchmark YAML files.

### 3. Run the benchmark suite

```bash
python -m benchmark.runner --repeat 3   # 3 passes; a single pass is not a measurement
python -m benchmark.report --last 36    # aggregates the last N logged runs
```

The benchmark checks the target sites first and skips tasks whose site is unavailable, so an outage does not masquerade as an agent failure. It also re-reads each task YAML on each pass, so avoid editing task files while a run is in progress.

Headless mode is the default unless the browser service was started headed. See [watching-the-benchmark-suite.md](watching-the-benchmark-suite.md) for the headed workflow.

### 4. Check for a regression before merging a change

```bash
python -m benchmark.regression_gate --repeat 3
```

This runs the suite, computes the mean pass rate, and compares it against the measured baseline in `benchmark/baseline.json`. The threshold is intentionally set below the observed noise floor rather than at an arbitrary round number; see [../analysis/regression-gate.md](../analysis/regression-gate.md).

## What remains intentionally CLI-only

- No live dashboard or run-trigger API. `agent/api.py` remains intentionally unimplemented.
- No headed mode inside Docker. This is not part of the current workflow.
