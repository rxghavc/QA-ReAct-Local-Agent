import importlib

MODULES = [
    "agent.api",
    "agent.loop",
    "agent.ollama_client",
    "agent.prompts",
    "agent.routing",
    "agent.tools",
    "benchmark.report",
    "benchmark.runner",
    "browser.server",
]


def test_modules_import():
    for name in MODULES:
        importlib.import_module(name)
