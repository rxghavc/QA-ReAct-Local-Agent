# Milestone 4: Getting the containers to actually talk to each other

## What this milestone was actually building

By the end of Milestone 3, the full agent loop worked, but only as two separate processes running directly on the laptop: the browser service (`uvicorn browser.server:app`) running in one terminal, and the agent loop (`python -m agent.loop`) running in another, both talking to each other over `localhost`, and both talking to Ollama also running directly on the laptop. This is fine for quick iteration, but it isn't how the project is meant to actually run. The plan's whole architecture (see the main README's diagram) calls for the agent and the browser to each run inside their own **Docker container**, kept separate from each other and from the host machine.

Milestone 4's job was to prove that same working system still works once it's actually split across two real, separate Docker containers, not just running as two windows on one laptop. This turned out to require exactly one line of configuration change, but it's a subtle one, and finding and understanding it is most of what this milestone was about.

## Background: containers, images, and Docker Compose, explained simply

A **Docker image** is like a frozen, self-contained snapshot of a tiny computer: a specific operating system, specific installed software, and a specific copy of this project's code, all bundled together into one file that can be copied anywhere and will behave identically. A **container** is a running instance of an image, an actual live process using that snapshot. You can start, stop, and throw away containers freely; the image itself doesn't change.

**Docker Compose** is a tool for describing several containers that need to run together as one system, using one YAML file (`docker-compose.yml` in this repo). This project defines two **services** in that file: `agent` and `browser`, each built from its own image (`agent/Dockerfile` and `browser/Dockerfile`).

The detail that matters most for this milestone: **when several containers are started together by the same Compose file, Compose automatically creates a private network for them, and each container can reach the others by using the other service's name as if it were a hostname.** So from inside the `agent` container, the browser service isn't reachable at `http://localhost:8001` (that would mean "port 8001 on this same container," which has nothing listening on it), it's reachable at `http://browser:8001`, using the literal word `browser` (the service's name in the YAML file) as the address. This is genuinely different from how things work when you just run two processes directly on your own laptop, where they really do share the same `localhost`.

There's a second, related piece of address plumbing already in this project's Compose file: `OLLAMA_HOST=http://host.docker.internal:11434`. Ollama itself is not a container in this setup, it runs directly on the host laptop (see the main README for why: getting a container to use the laptop's GPU for a 14-billion-parameter model is real friction that isn't the interesting part of this project). `host.docker.internal` is a special hostname that Docker provides specifically so that something *inside* a container can reach back out to services running on the host machine itself.

## The bug this milestone found

`agent/tools.py` (built in Milestone 3) has this line:

```python
BROWSER_SERVICE_URL = os.environ.get("BROWSER_SERVICE_URL", "http://localhost:8001")
```

The default value, `http://localhost:8001`, is exactly correct for Milestone 3's local setup, where both the agent loop and the browser service really were two processes on the same laptop sharing one `localhost`. But it is **silently wrong** the moment the agent process itself moves inside a container, because inside that container, `localhost` means "this container," and there is no browser service running inside the agent's own container, there never was one, the browser lives in a separate container entirely.

This is an easy category of bug to miss, because it doesn't fail loudly or obviously during development. The browser container on its own works completely fine, `curl http://localhost:8001/get_page_state` from the host laptop succeeds without any trouble, because Docker also publishes the browser container's port back out to the host laptop's own `localhost`. The bug only appears once something is actually running *inside* the agent container and trying to reach the browser *from there*, which is exactly the scenario this milestone specifically set out to test.

## The fix

One line added to `docker-compose.yml`, alongside the `OLLAMA_HOST` line that was already there:

```yaml
services:
  agent:
    ...
    environment:
      - OLLAMA_HOST=http://host.docker.internal:11434
      - BROWSER_SERVICE_URL=http://browser:8001
```

No code in `agent/` or `browser/` needed to change at all. `agent/tools.py` already read `BROWSER_SERVICE_URL` from an environment variable with a sensible local-development default; it just needed that environment variable actually set correctly for the containerized case.

## How this was verified, step by step, with real output

1. **Built both images**: `docker compose build`. Both the `agent` and `browser` images built successfully from their respective Dockerfiles.
2. **Started the browser container by itself**: `docker compose up -d browser`, then confirmed it was actually serving requests with `curl -o /dev/null -w "%{http_code}\n" http://localhost:8001/get_page_state`, which returned `200`.
3. **Ran the actual Milestone 3 task from inside the agent container**: `docker compose run --rm agent python -m agent.loop`. This overrides the agent image's normal startup command (which would otherwise start its FastAPI server) and instead runs the exact same hardcoded login task from Milestone 3, but this time the Python process executing it is running inside the `agent` container, talking to the `browser` container over the Compose network, and talking to Ollama on the host laptop via `host.docker.internal`.
4. **The task fully succeeded.** The trace showed all 5 steps completing cleanly: `navigate` to the login page, `type_text` for the username, `type_text` for the password, a `click` that this time used `selector: "button[type='submit']"` instead of the `#login` form id from the Milestone 3 run, then `report_done`, with the browser's own state confirming the URL had actually changed to `/secure` and the page's heading read "Secure Area." This time the model's self-report and the actual page state genuinely agreed.
5. **Re-ran the browser image's own smoke test**: `docker compose run --rm browser python browser/smoke_test.py`, the same check the CI pipeline's `docker-build` job runs to confirm a real Chromium binary can actually launch inside the built image, not just that the image built without errors. It printed `Chromium launched: 153.0.8010.12` and exited cleanly.
6. **Cleaned up** with `docker compose down`, and re-ran the full offline test suite (`pytest`, `ruff check`, `ruff format --check`, `mypy`) on the laptop directly, all still passing, since this milestone made no changes to any Python source file.

## An interesting side finding: the same model gave a different (and this time correct) answer

The Milestone 3 doc describes a run where the model picked `selector: "#login"` for the login button, which turned out to actually be the surrounding form's id, not the button's, causing the click to silently do nothing useful. On this milestone's run, using the exact same task instruction and the exact same model, it instead picked `selector: "button[type='submit']"`, a selector that correctly matches the actual submit button, and the login worked.

Nothing about the code changed between those two runs to cause this. Language models are not perfectly deterministic between separate calls, even with the same prompt, so the same instruction can produce two different, equally "reasonable-sounding" strategies on different attempts, one of which happens to work and one of which doesn't. This is a useful thing to have observed directly rather than just knowing abstractly: it's part of why Milestone 5 (the task suite and scorer) matters so much. A single successful run, or a single failed run, doesn't actually tell you how reliable the agent is. Only running the same tasks repeatedly and tracking a pass rate over many attempts can answer that honestly, which is exactly what the benchmark suite is for.

## What's next

Milestone 5 is about building that actual task suite and scorer: a set of tasks defined in YAML files, with success checked by a real, programmatic check against the browser's state (not by asking the model whether it thinks it succeeded), so that runs like the two different login attempts described above stop being anecdotes and start being data points in an actual pass rate.