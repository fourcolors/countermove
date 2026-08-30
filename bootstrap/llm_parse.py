"""Normalize free-text move phrasing through an LLM, then stop.

The model may only propose a canonical sentence. parse_move remains the
only function that can produce an executable move.
"""

import subprocess

from .move_parse import Rejection, parse_move

_TIMEOUT_SECONDS = 45

_QUESTION_FALLBACK = (
    "Tell me a specific price change, like: Raise Pro from $49 to $59."
)


def normalize_move(sentence, company, runner=None, strict_reply=None):
    """Return a canonical move sentence, or a Rejection.

    runner, if given, is runner(prompt) -> str. Tests inject a fake runner
    so the real grok CLI is never invoked from the suite.
    """
    prompt = _build_prompt(sentence, company)
    run = _default_runner if runner is None else runner
    try:
        raw = run(prompt)
        line = _last_nonempty_line(raw)
    except (KeyboardInterrupt, SystemExit, AssertionError):
        raise
    except Exception:
        return Rejection("llm_unavailable", _fallback_reply(sentence, company, strict_reply))
    if line.upper().startswith("REPLY:"):
        reply = line.split(":", 1)[1].strip()
        if not reply:
            reply = _fallback_reply(sentence, company, strict_reply)
        return Rejection("llm_reply", reply)
    return line


def _build_prompt(sentence, company):
    catalog = _plan_catalog(company)
    user_line = sentence if isinstance(sentence, str) else ""
    return (
        "You convert one user message into a single canonical price-move sentence.\n"
        "\n"
        "Company plans and current prices:\n"
        + catalog
        + "\n"
        "\n"
        "User message:\n"
        + user_line
        + "\n"
        "\n"
        "Reply with EXACTLY one line and nothing else.\n"
        "If the message is a price change on exactly one of the plans above, "
        "reply with this canonical form:\n"
        "Raise <Plan> from $<current> to $<new> effective <YYYY-MM-DD>\n"
        "Use Lower instead of Raise when the new price is lower than the current price.\n"
        "Omit the effective clause if the user did not give a date.\n"
        "Use the company's listed current price as $<current>.\n"
        "If the message is not a single-plan price move, reply with:\n"
        "REPLY: <one friendly plain-language sentence explaining what is supported, "
        "echoing what they asked>\n"
    )


def _plan_catalog(company):
    rows = []
    for plan in (company or {}).get("plans") or []:
        name = str(plan.get("id", "")).strip()
        if not name:
            continue
        rows.append("- %s at $%s" % (name, _shown_price(plan.get("price"))))
    if not rows:
        return "- (none listed)"
    return "\n".join(rows)


def _shown_price(price):
    try:
        number = float(price)
    except (TypeError, ValueError):
        return str(price)
    if number == int(number):
        return str(int(number))
    return str(number)


def _last_nonempty_line(raw):
    if raw is None:
        raise RuntimeError("empty grok output")
    if not isinstance(raw, str):
        raw = str(raw)
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    if not lines:
        raise RuntimeError("empty grok output")
    return lines[-1]


def _fallback_reply(sentence, company, strict_reply):
    if isinstance(strict_reply, str) and strict_reply.strip():
        return strict_reply
    rejected = parse_move(sentence if isinstance(sentence, str) else "", company)
    if isinstance(rejected, Rejection) and rejected.reply:
        return rejected.reply
    return _QUESTION_FALLBACK


def _default_runner(prompt):
    completed = subprocess.run(
        ["grok", "--no-leader", "-p", prompt],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=_TIMEOUT_SECONDS,
        text=True,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or "").strip() or (
            "grok exited %s" % completed.returncode
        )
        raise RuntimeError(detail)
    return completed.stdout
