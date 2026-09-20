# Guides

This section is for the day-to-day workflow: starting the project locally, running a task, watching the browser, and checking whether a change regressed the benchmark.

## Quick links

- [How to run the agent](how-to-run.md): local setup, execution commands, benchmark runs, and regression checks.
- [Watching the benchmark suite](watching-the-benchmark-suite.md): how to watch the full suite execute in a real browser window.

## Typical workflow

1. Start the browser service.
2. Ensure Ollama is serving the local model you want to use.
3. Run a benchmark or ad-hoc task.
4. Use the regression gate before merging a meaningful change.
