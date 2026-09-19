# Local Agentic Web-Testing Agent

A locally-run agentic QA web-testing tool: given a URL and a plain-language task, an agent plans steps, drives a real browser via Playwright, observes results, and self-corrects on failure, all sandboxed in Docker, running entirely on local models (qwen2.5-coder:14b) via Ollama.

## Setup

Requires Python 3.13, Docker Desktop, and [Ollama](https://ollama.com) running locally.

```bash
# Python env
pyenv local 3.13.5          # already pinned via .python-version
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
playwright install chromium

# Local models (planner + fast router)
ollama pull qwen2.5-coder:14b
ollama pull llama3.2:3b
```

Model sizing (`14b` planner + `3b` router) is scaled for a 24GB unified-memory machine, leaving headroom for the browser/Docker/OS. If you have more RAM/VRAM available, `qwen2.5-coder:24b` is a stronger drop-in planner.
