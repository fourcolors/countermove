"""Normalize free-text move phrasing through an LLM, then stop.

The model may only propose a canonical sentence. parse_move remains the
only function that can produce an executable move. A deterministic
anchor check then refuses a well-formed sentence whose target price or
plan is not in the user's own words.
"""

import re
import subprocess

from .move_parse import Rejection, parse_move

_TIMEOUT_SECONDS = 45

_QUESTION_FALLBACK = (
    "Tell me a specific price change, like: Raise Pro from $49 to $59."
)

_EFFECTIVE_TAIL = re.compile(r"(?i)\s+effective\b.*$")
_ISO_DATE_TOKEN = re.compile(r"\b20\d{2}-\d{2}-\d{2}\b")
_SLASH_DATE_TOKEN = re.compile(r"\b\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\b")
_MONTH_DAY_TOKEN = re.compile(
    r"(?i)\b(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|"
    r"nov(?:ember)?|dec(?:ember)?)\s+\d{1,2}\b"
)
_UNANCHORED_REPLY = (
    "I understood that as changing %s to $%s, but I need you to restate "
    "the move with the plan name and the new price spelled out."
)
_PLAN_ID_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.-]{0,39}$")
_CATALOG_PRICE = re.compile(r"^[0-9.]{1,12}$")
_CANONICAL_MOVE_LINE = re.compile(r"^(Raise|Lower)\b.*\$")


def normalize_move(sentence, company, runner=None, strict_reply=None):
    """Return a canonical move sentence, or a Rejection.

    runner, if given, is runner(prompt) -> str. Tests inject a fake runner
    so the real grok CLI is never invoked from the suite.
    """
    prompt = _build_prompt(sentence, company)
    run = _default_runner if runner is None else runner
    try:
        raw = run(prompt)
        line = _extract_reply_line(raw)
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


def accept_normalized_move(sentence, canonical, company, today=None):
    """Re-parse a model line and refuse it when the user's words do not anchor it.

    parse_move remains the only producer of an executable move. This check
    then requires the target price (and the plan, when the company has more
    than one) to appear in the original user sentence.
    """
    cleaned = strip_unanchored_effective(sentence, canonical)
    parsed = parse_move(cleaned, company, today=today)
    if not isinstance(parsed, dict):
        return parsed
    failed = check_anchors(sentence, parsed, company)
    if failed is not None:
        return failed
    return parsed


def strip_unanchored_effective(sentence, canonical):
    """Drop a trailing effective clause the model invented when the user gave no date."""
    line = canonical if isinstance(canonical, str) else ""
    if _user_gave_date(sentence):
        return line
    return _EFFECTIVE_TAIL.sub("", line).strip()


def check_anchors(sentence, move, company):
    """Return a Rejection when the parsed move is not grounded in the user sentence."""
    if not _price_anchored(sentence, move.get("to")):
        return _unanchored_rejection(move)
    if not _plan_anchored(sentence, move.get("plan"), company):
        return _unanchored_rejection(move)
    return None


def reconstruct_canonical(move):
    """Build the trace line from parsed move fields, never from the model string."""
    from_price = move["from"]
    to_price = move["to"]
    verb = "Lower" if to_price < from_price else "Raise"
    return "%s %s from $%s to $%s effective %s" % (
        verb,
        _shown_plan(move.get("plan")),
        _shown_price(from_price),
        _shown_price(to_price),
        move["effective"],
    )


def _user_gave_date(sentence):
    text = sentence if isinstance(sentence, str) else ""
    return bool(
        _ISO_DATE_TOKEN.search(text)
        or _SLASH_DATE_TOKEN.search(text)
        or _MONTH_DAY_TOKEN.search(text)
    )


def _price_anchored(sentence, to_price):
    text = sentence if isinstance(sentence, str) else ""
    digits = "".join(ch for ch in text if ch.isdigit())
    tokens = set()
    exact = _shown_price(to_price)
    if exact:
        tokens.add(str(exact))
    try:
        tokens.add(str(int(to_price)))
    except (TypeError, ValueError, OverflowError):
        pass
    for token in tokens:
        if token and (token in text or token in digits):
            return True
    return False


def _plan_anchored(sentence, plan_id, company):
    names = []
    for plan in (company or {}).get("plans") or []:
        name = str(plan.get("id", "")).strip()
        if name:
            names.append(name)
    if len(names) == 1:
        return True
    text = sentence if isinstance(sentence, str) else ""
    needle = str(plan_id or "").strip()
    if not needle:
        return False
    return needle.lower() in text.lower()


def _shown_plan(plan_id):
    name = str(plan_id or "")
    if not name:
        return name
    return name[0].upper() + name[1:]


def _unanchored_rejection(move):
    return Rejection(
        "llm_reply",
        _UNANCHORED_REPLY
        % (_shown_plan(move.get("plan")), _shown_price(move.get("to"))),
    )


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
        if not _PLAN_ID_TOKEN.match(name):
            continue
        try:
            shown = str(_shown_price(plan.get("price")))
        except (TypeError, ValueError, OverflowError):
            continue
        if not _CATALOG_PRICE.match(shown):
            continue
        rows.append("- %s at $%s" % (name, shown))
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


def _extract_reply_line(raw):
    if raw is None:
        raise RuntimeError("empty grok output")
    if not isinstance(raw, str):
        raw = str(raw)
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    allowed = [line for line in lines if _is_allowed_reply_line(line)]
    if len(allowed) != 1:
        raise RuntimeError("ambiguous grok output")
    return allowed[0]


def _is_allowed_reply_line(line):
    if line.upper().startswith("REPLY:"):
        return True
    return bool(_CANONICAL_MOVE_LINE.match(line))


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
