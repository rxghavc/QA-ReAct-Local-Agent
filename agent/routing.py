"""Stuck-detection support for agent/loop.py, and the record of why no
model call happens here.

The plan's Model Routing section proposed giving `llama3.2:3b` two cheap
jobs alongside the `qwen2.5-coder:14b` planner: "does this page state
indicate the task is likely complete?" and "is this the same failure as
last step?" Both were measured against the live model before anything was
wired in, and **both were rejected on evidence**. See
scripts/spike_3b_routing.py for the reproducible harness and
docs/milestones/07-model-routing.md for the full account.

In short: the 3b model tracks whichever answer the prompt's framing
emphasises rather than the content it is asked to judge. The completion
classifier answered "no" almost regardless of the page (including for a
"Thank you for your order!" checkout page). The same-failure classifier
was worse, because it looked like it worked: it passed hand-written test
cases, shipped, fired three times in a live benchmark run, and returned
the wrong answer all three times. Five prompt strategies were then
measured against real failures from that run plus genuinely-different
control pairs, and not one separated the two groups.

So `is_same_failure` below is deterministic. The judgement it needs to
make ("are these two failed actions aimed at the same thing?") is a
comparison of the targets the planner itself named, which is exactly the
kind of structural check code does precisely and for free, and which the
measurements show a 3b model does worse than not at all. Routing stays a
real, A/B-switchable part of the loop (`use_routing`), it just no longer
spends an inference call to get a less reliable answer.
"""

from __future__ import annotations

import re

# Targets shorter than this are only matched exactly. A two-character
# selector or label is too generic for a containment match to mean anything.
MIN_SUBSTRING_TARGET = 3

# Checked in the order the planner is most likely to have meant as "the
# thing I was aiming at" when it passed more than one.
TARGET_KEYS = ("selector", "text", "url")

# Everything that isn't a letter or digit is a word break. This is what
# lets a visible label and the selector for the same control compare
# equal word for word: `#add-to-cart-sauce-labs-backpack` and
# "Add to cart" both reduce to word sequences starting "add to cart",
# where a literal string comparison sees nothing in common.
_WORDS = re.compile(r"[a-z0-9]+")


def failure_target(call: dict) -> str:
    """The normalised thing a tool call was aimed at, as a word sequence."""
    arguments = call.get("arguments") or {}
    for key in TARGET_KEYS:
        value = arguments.get(key)
        if value:
            return " ".join(_WORDS.findall(str(value).casefold()))
    return ""


def _contains_whole_words(longer: str, shorter: str) -> bool:
    """Does `shorter` appear inside `longer` as a run of complete words?

    Both arguments are already single-space-separated word sequences, so
    padding each with spaces makes a plain substring test word-aligned.
    Matching on whole words is what keeps the separator normalisation
    above from inventing false positives: "art" must not match inside
    "smart button", and "a" must not match inside "aside".
    """
    return f" {shorter} " in f" {longer} "


def is_same_failure(
    previous_call: dict,
    previous_error: str,
    current_call: dict,
    current_error: str,
) -> bool:
    """Is the agent stuck on the same thing, though the two failed calls
    aren't byte-for-byte identical?

    True when both calls were aimed at the same target, compared as
    case-insensitive word sequences with separators treated as word
    breaks, and with a whole-word containment check either way round. Two
    real patterns from the Milestone 5 and 7 benchmark runs need that,
    and exact matching catches neither:

    - The planner guesses a *different* wrong label each attempt, padding
      or truncating it ("CHECKOUT" then "CHECKOUT: YOUR INFORMATION").
    - The planner switches between a visible label and a selector for the
      same control (click text="Add to cart", then wait_for
      selector="#add-to-cart-sauce-labs-backpack"), which is one
      mistake wearing two different spellings.

    The error strings are accepted but not inspected. They carry no signal
    the targets don't already carry, and the same-failure classifier that
    did read them is the one the spike rejected. They stay in the
    signature because the loop has them and a future failure-kind
    comparison would need them.

    False when either call named no target, which keeps the original
    conservative bias: a missed dedup costs one ordinary retry, while a
    wrong "same" suppresses a re-plan the planner actually needed.
    """
    previous_target = failure_target(previous_call)
    current_target = failure_target(current_call)
    if not previous_target or not current_target:
        return False
    if previous_target == current_target:
        return True
    shorter, longer = sorted((previous_target, current_target), key=len)
    if len(shorter) < MIN_SUBSTRING_TARGET:
        return False
    return _contains_whole_words(longer, shorter)