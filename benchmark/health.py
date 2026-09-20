"""Pre-flight reachability checks for the sites a task depends on.

This exists because of a specific incident in Milestone 7:
`the-internet.herokuapp.com` started returning HTTP 503 partway through an
A/B comparison of the suite. Three of the seven tasks depend on that site,
and the outage hit them inconsistently across the two halves of the
comparison, so one half scored 4/7 and the other 2/7 for reasons that had
nothing to do with the code being compared. Worse, those runs looked
exactly like agent failures: the planner navigated, got an "Application
Error" page, correctly reported itself blocked, and the scorer recorded a
fail.

**An unreachable site is a broken measurement, not a failing agent.** So a
task whose site is down is skipped and scored as neither pass nor fail,
and the suite summary says how many were skipped. That keeps a pass rate
honest at the cost of sometimes reporting fewer results, which is the
right trade: a quietly wrong number is worse than a visibly incomplete
one. See docs/milestones/07-model-routing.md for the incident.
"""

from __future__ import annotations

import re

import httpx

# Tasks put their target URL in the instruction prose rather than a
# separate field, so it is read back out rather than duplicated. A task
# whose instruction has no URL, or whose first URL is not the one worth
# checking, can set `health_check_url` explicitly instead.
_URL = re.compile(r"https?://[^\s'\"<>)]+")

HEALTH_TIMEOUT_SECONDS = 10


def health_check_url(task: dict) -> str | None:
    """The URL whose reachability decides whether this task can be scored."""
    explicit = task.get("health_check_url")
    if explicit:
        return str(explicit)
    match = _URL.search(task.get("instruction", ""))
    return match.group(0).rstrip(".,") if match else None


def check_url(url: str) -> tuple[bool, str]:
    """Is `url` reachable right now? Returns (healthy, human-readable detail).

    Any status below 400 counts as reachable. This deliberately does not
    care whether the page is the *right* page, only that the site is
    serving something: judging content is the scorer's job, and a redirect
    or a login wall is not an outage.
    """
    try:
        response = httpx.get(url, timeout=HEALTH_TIMEOUT_SECONDS, follow_redirects=True)
    except httpx.HTTPError as exc:
        return False, f"{type(exc).__name__}: {exc}"
    if response.status_code >= 400:
        return False, f"HTTP {response.status_code}"
    return True, f"HTTP {response.status_code}"


def task_skip_reason(task: dict) -> str | None:
    """Why this task cannot be scored right now, or None if it can be.

    A task with no discoverable URL returns None: there is nothing to
    pre-flight, which is the right answer for a task that is not about
    reaching a particular site (an ambiguous-instruction negative test,
    for example).
    """
    url = health_check_url(task)
    if url is None:
        return None
    healthy, detail = check_url(url)
    if healthy:
        return None
    return f"{url} unreachable ({detail})"
