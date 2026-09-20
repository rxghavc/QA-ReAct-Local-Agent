# Watching the benchmark suite

The browser service decides whether the run is headed or headless, not the benchmark command itself. `benchmark/runner.py` talks to the same browser service over HTTP that `agent/loop.py` uses, and the behavior is controlled by the `BROWSER_HEADLESS` environment variable when the browser service starts.

To watch the suite run in a real Chromium window:

```bash
# terminal 1 , headed
BROWSER_HEADLESS=false uvicorn browser.server:app --port 8001

# terminal 2
python -m benchmark.runner --repeat 3
```

## What to expect

- It takes time: a single suite pass is typically several minutes, and `--repeat 3` is a sustained run rather than a quick smoke test.
- The terminal does not stream step-by-step reasoning while the run is in progress. The browser window is the real-time signal.
- The project’s official benchmark numbers were measured in headless mode, which matches the Docker and CI workflow. Headed mode is mainly for observation or a recorded demo.
- If you want to see the full suite end to end, run the headed browser service and then trigger `benchmark.runner --repeat 3`.