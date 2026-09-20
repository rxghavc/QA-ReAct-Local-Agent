# Local Browser Automation Agent

A local browser agent that takes a plain-language task, opens a real browser, and works through the problem step by step until it reaches a real outcome. It is designed to be local-first, observable, and benchmarkable rather than opaque or self-reporting.

I built and fine-tuned this agent on an M4 MacBook with roughly 24GB of RAM. The setup is intentionally minimal: Ollama runs the model locally, Docker keeps the browser/runtime layer isolated, and the benchmark checks the final browser state instead of trusting the agent to tell us it succeeded.

The core idea is simple: a small local model, a real browser, a constrained set of tools, and a feedback loop that keeps going until the task is complete or it hits a genuine stop condition. That makes it useful as both a practical browser automation project and a clean way to study agent behaviour in a measurable environment.

## Demo

Watch the agent take a plain-language task, drive a real browser, and verify the result:

<video controls width="100%">
	<source src="https://github.com/user-attachments/assets/dda80a2b-681d-42d4-b85d-0389ba8e9dd0" type="video/mp4">
	Your browser does not support embedded video.
</video>

Can't see the video? [Open the demo video directly](assets/QA-Testing-Agent-Demo.mp4)

The recording starts by launching the headed browser service and the local agent in two tiled terminal windows. The browser stays open for the full session while each task is pasted into the agent terminal and run against a real Chromium window.

The three clips show:

- **Checkout flow:** a longer SauceDemo workflow covering login, adding a product to the cart, checkout, and order completion. This demonstrates the agent planning across multiple pages and actions.
- **Dynamic loading:** the agent starts a delayed page element, waits for it to finish loading, and only then reports completion instead of reading the page too early.
- **Impossible login:** the agent receives invalid credentials and reports that it is blocked rather than hallucinating a successful login. This demonstrates the negative-test behavior built into the benchmark.

**All three clips passed their respective benchmark checks**! 🎉

**For the full task suite runbook, benchmark workflow, and headed-browser mode**, see [docs/guides/how-to-run.md](docs/guides/how-to-run.md).

## Quick start

Requirements:

- Python 3.13
- Docker Desktop
- [Ollama](https://ollama.com) installed and running locally
- enough local RAM for model inference; 24GB unified memory is a comfortable setup, and 16GB can work but will be noticeably slower

```bash
# create and activate the environment
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
playwright install chromium

# pull the model used by the project
ollama pull qwen2.5-coder:14b

# start the browser service
uvicorn browser.server:app --port 8001

# run one ad-hoc task
python -m agent.loop "Go to https://www.saucedemo.com/, log in with username 'standard_user' and password 'secret_sauce', add the first product to the cart, and complete checkout." --max-steps 15
```

For the full runbook, benchmark workflow, and headed-browser mode, see [docs/guides/how-to-run.md](docs/guides/how-to-run.md).

## Current measured status

This project reports benchmark results as a range over repeated runs rather than a single cherry-picked number. The metric table below reflects the most recent measured run profile, with pass rate tracked across repeated benchmark passes.

- suite pass rate over 3 runs: 83% to 92%, mean 89%
- self-report accuracy: 93%
- average steps per task run: 5.6

Note: the **“negative” tasks are intentionally designed to test graceful failure**, not successful completion. For those cases, the right behavior is to recognise an impossible or ambiguous task and either report the block or ask for clarification.

| Task | Tier | Pass rate | Avg steps | Avg wall clock |
|---|---|---|---|---|
| task_01_the_internet_login | 1 | 3/3 (100%) | 5.0 | 27.2s |
| task_02_saucedemo_login | 1 | 3/3 (100%) | 5.0 | 27.0s |
| task_03_saucedemo_add_to_cart | 2 | 3/3 (100%) | 6.0 | 27.1s |
| task_04_saucedemo_checkout | 2 | 3/3 (100%) | 13.7 | 50.8s |
| task_05_saucedemo_logout | 2 | 3/3 (100%) | 7.0 | 30.3s |
| task_06_dynamic_loading | 3 | 3/3 (100%) | 4.0 | 23.0s |
| task_07_js_confirm_dialog | 3 | 3/3 (100%) | 4.0 | 23.6s |
| task_09_pagination_count | 4 | 3/3 (100%) | 4.0 | 24.3s |
| task_10_invalid_login_rejected | 4 | 3/3 (100%) | 5.0 | 30.4s |
| **task_11_impossible_login** | **negative** | **3/3 (100%)** | 6.0 | 27.4s |
| **task_12_ambiguous_instruction** | **negative** | **2/3 (67%)** | 2.0 | 17.7s |
| task_08_table_extraction | 4 | 0/3 (0%) | 6.0 | 29.7s |

The strongest recent improvement came from fixing a real selector issue in the browser observation layer, not from changing the underlying model. For the detailed findings, see [docs/analysis/context-optimization.md](docs/analysis/context-optimization.md) and [docs/analysis/regression-gate.md](docs/analysis/regression-gate.md).

## Tech stack

| Layer | Choice | Notes |
|---|---|---|
| Local inference | Ollama, serving `qwen2.5-coder:14b` | Runs locally on the same machine as the agent; the model is not hosted remotely. |
| Agent orchestration | Python, hand-rolled ReAct loop (`agent/loop.py`) | The system is deliberately simple and explicit rather than framework-heavy. |
| Browser automation | Playwright (Python) | Uses a persistent browser session and a real Chromium page. |
| Sandboxing | Docker Compose | Keeps the agent and browser layer separate, mirroring the project runtime. |
| API layer | FastAPI on the browser side | The project is CLI-first and does not depend on a web UI. |
| Benchmarking | YAML task definitions plus `benchmark/runner.py` | Tasks are scored against real browser state rather than a model self-report. |
| Logging | Structured JSON traces in `logs/` | Enables reporting, regression tracking, and post-run analysis. |

## Agent architecture

```text
┌──────────────────────┐      HTTP      ┌──────────────────────┐
│   agent container    │  ───────────▶  │  browser container   │
│  (agent/Dockerfile)  │                │ (browser/Dockerfile) │
└──────────────────────┘                └──────────────────────┘
```

- **Agent layer**: `agent/loop.py` runs the ReAct loop, calls the model through `agent/ollama_client.py`, and dispatches tool calls through `agent/tools.py`.
- **Browser layer**: `browser/server.py` exposes a FastAPI service around a persistent Playwright browser session, with a single Chromium page reused for the life of the process.
- **Benchmark layer**: `benchmark/runner.py` executes YAML task definitions, preflights site health, and scores the actual browser outcome instead of trusting the model's own self-report.

## Repository map

- [agent/](agent/): orchestration, prompts, model client, and tool dispatch
- [browser/](browser/): Playwright-backed browser session and browser service
- [benchmark/](benchmark/): task definitions, health checks, scoring, reporting, and regression gate
- [tests/](tests/): deterministic checks for tool and scorer behavior
- [docs/](docs/): project documentation, analysis, architecture notes, guides, and milestones

## Documentation map

- [docs/guides/README.md](docs/guides/README.md): how to run the project locally
- [docs/architecture/README.md](docs/architecture/README.md): system design and infrastructure tradeoffs
- [docs/analysis/README.md](docs/analysis/README.md): measured findings and lessons learned
- [docs/research/README.md](docs/research/README.md): experiments and optimization notes
- [docs/milestones/README.md](docs/milestones/README.md): the numbered project history
