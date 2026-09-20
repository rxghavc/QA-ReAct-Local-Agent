# Can I watch the full 12-task suite run in the browser?

Yes, **headedness is a property of the browser service
process, not of which command drives it.** `benchmark/runner.py` talks
to whatever browser service is up over HTTP, the exact same way
`agent/loop.py` does. Neither command controls headed/headless itself;
`browser/actions.py`'s `BrowserSession` does, based on the
`BROWSER_HEADLESS` environment variable the service was started with.

So this plays out all 12 tasks, repeated, live in a real Chromium
window, one after another:

```bash
# terminal 1 — headed, same as for filming
BROWSER_HEADLESS=false uvicorn browser.server:app --port 8001

# terminal 2
python -m benchmark.runner --repeat 3
```

## What to actually expect

- **It takes a while.** Based on this project's own measurements, one
  pass of all 12 tasks runs roughly 5-8 minutes, so `--repeat 3` is
  more like 15-25 minutes of continuous watching, not a quick clip.
- **The terminal shows nothing live, in either command.** This is not
  specific to `benchmark.runner`: `agent/loop.py` also only prints its
  result once the task is fully done, never a running commentary as it
  goes. The browser window is the only real-time signal either way;
  neither command streams the model's step-by-step reasoning to the
  terminal as it happens.
- **The README's actual reported numbers were measured headless**
  (matching Docker/CI, see `docs/how-to-run.md`). Running headed to
  watch shouldn't change the agent's behavior or results in any way
  that matters, since it's the same browser session and the same DOM
  either way, just rendered on screen instead of not, but headless
  remains what's officially reported as this project's benchmark.
- **Curious what the whole suite looks like end to end, no editing
  needed:** headed + `benchmark.runner --repeat 3`, as above.