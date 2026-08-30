"""Parse one typed sentence into a move, or a typed rejection.

Questions and non-price requests never produce a move, so nothing downstream
builds a tree from them. Plan names are matched against the company; a name
that is not on the company is refused rather than invented.
"""

from datetime import date, datetime, timedelta
import re

DEFAULT_EFFECTIVE_DAYS = 9
ACTION = "open_pr"

_WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}

_MONTHS = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}

_PRICE_VERB = re.compile(
    r"(?i)\b(raise|increase|hike|cut|lower|drop|reduce|decrease|change|set)\b"
)
_PLAN_AFTER_VERB = re.compile(
    r"(?i)\b(?:raise|increase|hike|cut|lower|drop|reduce|decrease|change|set)\s+"
    r"(?:the\s+)?([A-Za-z][A-Za-z0-9_-]*)"
)
_PLAN_STOPWORDS = frozenset(
    {
        "prices",
        "price",
        "plan",
        "plans",
        "our",
        "my",
        "a",
        "an",
        "it",
        "this",
        "that",
        "from",
        "to",
        "by",
        "for",
        "on",
        "your",
    }
)
_FROM_TO = re.compile(
    r"(?i)from\s+\$?\s*(\d+(?:\.\d+)?)\s+to\s+\$?\s*(\d+(?:\.\d+)?)"
)
_TO_PRICE = re.compile(r"(?i)\bto\s+\$?\s*(\d+(?:\.\d+)?)\b")
_QUESTION_OPENER = re.compile(
    r"(?i)^\s*(should|could|would|can|may|shall|do|does|did|is|are|was|"
    r"were|what|why|how|when|who|whom|which)\b"
)
_NEXT_WEEKDAY = re.compile(
    r"(?i)\bnext\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b"
)
_ISO_DATE = re.compile(r"\b(20\d{2}-\d{2}-\d{2})\b")
_MONTH_DAY = re.compile(
    r"(?i)\b(?:on\s+)?("
    r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|"
    r"nov(?:ember)?|dec(?:ember)?"
    r")\s+(\d{1,2})(?:,?\s*(\d{4}))?"
)

_QUESTION_REPLY = (
    "Tell me a specific price change, like: Raise Pro from $49 to $59."
)
_OUT_OF_SCOPE_REPLY = (
    "Only price moves on one plan are supported today. "
    "Describe a price change, like: Raise Pro from $49 to $59."
)


class Rejection:
    """Typed refusal. kind is 'question', 'out_of_scope', or 'unknown_plan'."""

    def __init__(self, kind, reply):
        self.kind = kind
        self.reply = reply

    def __repr__(self):
        return "Rejection(kind=%r, reply=%r)" % (self.kind, self.reply)

    def __eq__(self, other):
        return (
            isinstance(other, Rejection)
            and self.kind == other.kind
            and self.reply == other.reply
        )


def parse_move(text, company, today=None):
    """Return a move dict or a Rejection. Does not mutate company or any tree."""
    if not isinstance(text, str) or not text.strip():
        return Rejection("question", _QUESTION_REPLY)

    stripped = text.strip()
    if _is_question(stripped):
        return Rejection("question", _QUESTION_REPLY)

    from_price, to_price = _prices(stripped)
    plan = _named_plan(stripped, company)

    if _PRICE_VERB.search(stripped) and to_price is not None:
        if plan is None:
            return _unknown_plan(stripped, company)
        if from_price is None:
            from_price = _as_number(plan["price"])
        effective = _effective_date(stripped, today)
        return {
            "plan": plan["id"],
            "from": from_price,
            "to": to_price,
            "action": ACTION,
            "effective": effective.isoformat(),
        }

    if _PRICE_VERB.search(stripped):
        return Rejection("question", _QUESTION_REPLY)

    return Rejection("out_of_scope", _OUT_OF_SCOPE_REPLY)


def _is_question(text):
    if text.endswith("?"):
        return True
    return bool(_QUESTION_OPENER.match(text))


def _prices(text):
    match = _FROM_TO.search(text)
    if match:
        return _as_number(match.group(1)), _as_number(match.group(2))
    match = _TO_PRICE.search(text)
    if match:
        return None, _as_number(match.group(1))
    return None, None


def _named_plan(text, company):
    plans = list(company.get("plans") or [])
    mentioned = _mentioned_plan_token(text)
    if mentioned is not None:
        for plan in plans:
            if str(plan.get("id", "")).strip().lower() == mentioned.lower():
                return plan
        return None
    lowered = text.lower()
    ranked = sorted(
        plans, key=lambda item: len(str(item.get("id", ""))), reverse=True
    )
    for plan in ranked:
        plan_id = str(plan.get("id", "")).strip()
        if not plan_id:
            continue
        if re.search(r"\b%s\b" % re.escape(plan_id.lower()), lowered):
            return plan
    if len(plans) == 1:
        return plans[0]
    return None


def _mentioned_plan_token(text):
    match = _PLAN_AFTER_VERB.search(text)
    if not match:
        return None
    token = match.group(1)
    if token.lower() in _PLAN_STOPWORDS:
        return None
    return token


def _unknown_plan(text, company):
    names = []
    for plan in company.get("plans") or []:
        plan_id = str(plan.get("id", "")).strip()
        if plan_id:
            names.append(plan_id)
    mentioned = _mentioned_plan_token(text)
    if names:
        listed = ", ".join(names)
        if mentioned:
            reply = (
                "I will not guess a plan called %s; it is not on the company. "
                "The plans I have are: %s. "
                "Tell me which of those to change and the new price."
            ) % (mentioned, listed)
        else:
            reply = (
                "I will not guess a plan that is not on the company. "
                "The plans I have are: %s. "
                "Tell me which of those to change and the new price."
            ) % listed
    else:
        reply = (
            "I will not guess a plan that is not on the company. "
            "Add a plan on the company card first, then tell me the price change."
        )
    return Rejection("unknown_plan", reply)


def _effective_date(text, today):
    today_date = _as_date(today)
    weekday = _NEXT_WEEKDAY.search(text)
    if weekday:
        return _next_weekday(today_date, weekday.group(1))
    iso = _ISO_DATE.search(text)
    if iso:
        return date.fromisoformat(iso.group(1))
    month_day = _MONTH_DAY.search(text)
    if month_day:
        month = _MONTHS[month_day.group(1).lower()]
        day = int(month_day.group(2))
        year = int(month_day.group(3)) if month_day.group(3) else today_date.year
        try:
            resolved = date(year, month, day)
        except ValueError:
            return today_date + timedelta(days=DEFAULT_EFFECTIVE_DAYS)
        if month_day.group(3) is None and resolved < today_date:
            try:
                resolved = date(year + 1, month, day)
            except ValueError:
                return today_date + timedelta(days=DEFAULT_EFFECTIVE_DAYS)
        return resolved
    return today_date + timedelta(days=DEFAULT_EFFECTIVE_DAYS)


def _next_weekday(today_date, name):
    target = _WEEKDAYS[name.lower()]
    ahead = (target - today_date.weekday()) % 7
    if ahead == 0:
        ahead = 7
    return today_date + timedelta(days=ahead)


def _as_date(value):
    if value is None:
        return date.today()
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return date.fromisoformat(value[:10])
    raise TypeError("today must be a date")


def _as_number(value):
    number = float(value)
    if number == int(number):
        return int(number)
    return number
