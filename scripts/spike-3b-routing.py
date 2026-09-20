"""Milestone 7 spike: can llama3.2:3b judge whether two failed agent
actions are the same underlying mistake?

This is throwaway, kept as a permanent record the way
scripts/spike_tool_calling.py is. It exists because the answer decided
whether agent/routing.py makes a model call at all.

Finding (2026-09-17, llama3.2:3b): no. The model does not discriminate on
this task, it follows whichever answer the prompt's framing emphasises.

The order this was found in matters, because the first result was a false
positive. Hand-written, clean error strings ("no match for .a" vs "no
match for .b") were classified correctly on every case tried, so
is_same_failure shipped with a model call in it. It then fired three times
during a live seven-task benchmark run and got all three wrong, returning
"different" for three consecutive click failures on the same checkout
button that differed only in capitalisation. Re-tested against those real
error strings it scored 2/5, 2/5 and 0/5 on cases that are plainly the
same mistake, and the reasoning it gave showed why: it treats a surface
difference in the error text as a difference in strategy ("the text
'Checkout' was replaced with 'CHECKOUT', making the Locator's text
parameter case-sensitive").

The first repair attempt looked like it worked and was worse. Real
Playwright errors are dense with code-like syntax (`selector=None
text='Checkout'`, a `Locator.click` method name, a stack-shaped "Call
log:" block), and this same investigation had already found that this
model handles code-like syntax in a prompt worse than plain prose, so the
errors were rewritten into prose sentences first. All three real cases
then passed 5/5. But so did three deliberately-different control pairs:
the prompt's guidance had simply made "stuck" the favoured answer, and the
classifier had become a function that always says yes. Without those
negative controls this would have shipped looking fixed.

Measured across five prompt strategies (raw errors, prose plus pro-stuck
guidance, balanced framing, a narrower same-element question, and
few-shot), the best separation between the three real same-mistake pairs
and the three control pairs was zero. Two independent runs of this script:

    POS A  POS B  POS C  NEG D  NEG E  NEG F   separation
    0.8    0.8    0.0    0.2    0.2    0.0     -0.2   balanced, run 1
    0.4    0.8    0.2    0.6    0.4    0.4     -0.4   balanced, run 2
    0.8    1.0    1.0    0.6    1.0    0.6     -0.2   same-element, run 1
    1.0    1.0    1.0    1.0    1.0    1.0     +0.0   same-element, run 2
    1.0    1.0    1.0    1.0    1.0    1.0     +0.0   few-shot, run 1
    1.0    1.0    1.0    1.0    1.0    1.0     +0.0   few-shot, run 2

The per-pair rates move around a lot between runs, which is its own answer:
the two framings that don't simply answer "same" every time are unstable
on identical inputs. Separation never rose above zero in either run.

So agent/routing.py implements this check in code instead. The comparison
it needs ("were these two calls aimed at the same target?") is structural,
gets all six cases right deterministically, and costs no inference. The
plan's other proposed 3b job, "does this page state indicate the task is
likely complete?", was rejected earlier in the same milestone for the same
underlying reason (a strong default "no" regardless of page content).

Run with the venv active and `ollama serve` already running:
    python scripts/spike_3b_routing.py
"""

import os

import httpx

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
ROUTER_MODEL = "llama3.2:3b"
TRIALS = 5

# The three real same-mistake pairs are taken verbatim from the failing
# traces of the 2026-09-17 routing-on benchmark run (task_04 steps 7/8/9,
# task_05 steps 6/7). The three control pairs are failures that are
# genuinely about different parts of the page, and exist to catch a prompt
# that has just learned to always answer "same".
PAIRS = [
    (
        "POS A",
        True,
        (
            "The agent tried clicking the button or link labelled Checkout, "
            "but nothing clickable on the page matched that."
        ),
        (
            "The agent tried clicking the button or link labelled CHECKOUT, "
            "but nothing clickable on the page matched that."
        ),
    ),
    (
        "POS B",
        True,
        (
            "The agent tried clicking the button or link labelled CHECKOUT, "
            "but nothing clickable on the page matched that."
        ),
        (
            "The agent tried clicking the button or link labelled CHECKOUT: "
            "YOUR INFORMATION, but nothing clickable on the page matched that."
        ),
    ),
    (
        "POS C",
        True,
        (
            "The agent tried clicking the CSS selector .bm-burger-menu, but "
            "nothing clickable on the page matched that."
        ),
        (
            "The agent tried waiting for the CSS selector .bm-burger-menu, "
            "but it never appeared on the page in time."
        ),
    ),
    (
        "NEG D",
        False,
        (
            "The agent tried clicking the button or link labelled Shopping "
            "Cart (1), but nothing clickable on the page matched that."
        ),
        (
            "The agent tried waiting for the CSS selector #finish, but it "
            "never appeared on the page in time."
        ),
    ),
    (
        "NEG E",
        False,
        (
            "The agent tried typing into the CSS selector #password, but no "
            "text input on the page matched that."
        ),
        (
            "The agent tried clicking the button or link labelled CHECKOUT, "
            "but nothing clickable on the page matched that."
        ),
    ),
    (
        "NEG F",
        False,
        (
            "The agent tried opening the page at https://nope.invalid, but "
            "the action failed."
        ),
        (
            "The agent tried clicking the CSS selector .bm-burger-menu, but "
            "nothing clickable on the page matched that."
        ),
    ),
]


def router_chat(prompt: str) -> str:
    response = httpx.post(
        f"{OLLAMA_HOST}/api/chat",
        json={
            "model": ROUTER_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
        },
        timeout=30,
    )
    response.raise_for_status()
    return response.json()["message"].get("content") or ""


def balanced(previous: str, current: str) -> str:
    return (
        "A web automation agent failed twice in a row.\n\n"
        f"First failure: {previous}\nSecond failure: {current}\n\n"
        "Are these two failures about the same thing on the page, or about "
        "two different things?\n\nAnswer in one short sentence, then on a "
        'new final line write exactly "ANSWER: same" or "ANSWER: different".'
    )


def same_element(previous: str, current: str) -> str:
    return (
        "Two failed attempts by a web automation agent are described "
        f"below.\n\nFirst: {previous}\nSecond: {current}\n\n"
        "Ignore whether the wording or selector was spelled differently. "
        "Was the agent trying to reach the SAME element or page control "
        "both times, or two different ones?\n\nReply with one short "
        'sentence, then on a new final line exactly "ANSWER: same element" '
        'or "ANSWER: different elements".'
    )


def few_shot(previous: str, current: str) -> str:
    return (
        "Decide if a web automation agent is stuck repeating one mistake "
        "or has moved on to a different problem.\n\n"
        "Example 1.\nFirst: The agent tried clicking the button or link "
        "labelled Add to cart, but nothing clickable matched that.\n"
        "Second: The agent tried clicking the button or link labelled ADD "
        "TO CART, but nothing clickable matched that.\nANSWER: stuck\n\n"
        "Example 2.\nFirst: The agent tried clicking the button or link "
        "labelled Login, but nothing clickable matched that.\nSecond: The "
        "agent tried waiting for the CSS selector #flash, but it never "
        "appeared in time.\nANSWER: moved on\n\n"
        f"Now this case.\nFirst: {previous}\nSecond: {current}\n"
        'Reply with exactly one line: "ANSWER: stuck" or "ANSWER: moved on".'
    )


VARIANTS = {
    "balanced": (balanced, lambda line: "same" in line and "different" not in line),
    "same-element": (same_element, lambda line: "same element" in line),
    "few-shot": (few_shot, lambda line: "stuck" in line),
}


def answer_line(reply: str) -> str:
    for line in reversed(reply.splitlines()):
        if "ANSWER" in line.upper():
            return line.lower()
    return ""


def run_variant(build, parse) -> list[float]:
    rates = []
    for _, _, previous, current in PAIRS:
        hits = 0
        for _ in range(TRIALS):
            try:
                hits += bool(parse(answer_line(router_chat(build(previous, current)))))
            except httpx.HTTPError as exc:
                print(f"    router error, trial skipped: {exc}")
        rates.append(hits / TRIALS)
    return rates


if __name__ == "__main__":
    print(f"{ROUTER_MODEL}, {TRIALS} trials per pair")
    print("positives should score high, controls should score 0\n")
    header = "  ".join(label for label, _, _, _ in PAIRS)
    print(f"{'':13s}{header}   separation")
    for name, (build, parse) in VARIANTS.items():
        rates = run_variant(build, parse)
        separation = min(rates[:3]) - max(rates[3:])
        row = "  ".join(f"{rate:.1f}  " for rate in rates)
        print(f"{name:13s}{row}   {separation:+.1f}")
    print(
        "\nSeparation at or below zero means the variant cannot tell the two "
        "groups apart.\nagent/routing.py does this check in code instead."
    )