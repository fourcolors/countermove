"""Structured-fact extraction for untrusted scraped pages.

Price comes out as a number or None, never raw text.
Facts are schema-shaped and drop instruction-like content.
"""

import html
import json
import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCHEMA_PATH = _REPO_ROOT / "contracts" / "persona_card.schema.json"

_INSTRUCTION_MARKERS = (
    "ignore previous",
    "ignore all previous",
    "ignore all instructions",
    "you are now",
    "system:",
    "disclose the tool",
    "treat this page as trusted",
    "override the extractor",
    "set notes to pwned",
    "new instructions",
    "disregard previous",
    "developer mode",
    "jailbreak",
    "trusted system input",
)

_PRO_PRICE = re.compile(
    r"(?is)(?:data-plan\s*=\s*[\"']pro[\"'][^>]*>|\bpro\b).{0,160}?\$\s*(\d+(?:\.\d{1,2})?)"
)
_PRO_PRICE_AFTER = re.compile(
    r"(?is)\$\s*(\d+(?:\.\d{1,2})?).{0,80}\bpro\b"
)
_DOLLAR_PRICE = re.compile(r"\$\s*(\d+(?:\.\d{1,2})?)\b")
_NOTES_OK = re.compile(
    r"^(?:price (?:unknown|\d+(?:\.\d+)?)(?:; plan count \d+)?)?$"
)


def _load_schema():
    with _SCHEMA_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


_SCHEMA = _load_schema()


def _contains_instruction(text):
    if not isinstance(text, str) or not text:
        return False
    lower = text.lower()
    if any(marker in lower for marker in _INSTRUCTION_MARKERS):
        return True
    if "ignore" in lower and "instruction" in lower:
        return True
    return False


def _strip_hostile_markup(text):
    cleaned = re.sub(r"<!--.*?-->", " ", text, flags=re.DOTALL)
    cleaned = re.sub(r"(?is)<script\b[^>]*>.*?</script>", " ", cleaned)
    cleaned = re.sub(r"(?is)<style\b[^>]*>.*?</style>", " ", cleaned)
    cleaned = re.sub(
        r"(?is)<(?P<tag>[a-z][a-z0-9]*)\b[^>]*\bhidden\b[^>]*>.*?</(?P=tag)\s*>",
        " ",
        cleaned,
    )
    kept = []
    for line in cleaned.splitlines():
        if _contains_instruction(line):
            continue
        kept.append(line)
    return "\n".join(kept)


def _to_plain(text):
    plain = re.sub(r"<[^>]+>", " ", text)
    plain = html.unescape(plain)
    return re.sub(r"\s+", " ", plain).strip()


def _as_price(raw):
    value = float(raw)
    if value != value:  # NaN
        return None
    return value


def extract_price(markdown_or_html):
    """Return a price as float, or None when nothing parseable is present."""
    if not isinstance(markdown_or_html, str) or not markdown_or_html.strip():
        return None
    html_text = _strip_hostile_markup(markdown_or_html)
    match = _PRO_PRICE.search(html_text)
    if match:
        return _as_price(match.group(1))
    match = _PRO_PRICE_AFTER.search(html_text)
    if match:
        return _as_price(match.group(1))
    plain = _to_plain(html_text)
    found = _DOLLAR_PRICE.findall(plain)
    if len(found) == 1:
        return _as_price(found[0])
    if len(found) > 1:
        near = re.search(
            r"(?i)\bpro\b.{0,80}\$\s*(\d+(?:\.\d{1,2})?)",
            plain,
        )
        if near:
            return _as_price(near.group(1))
        near = re.search(
            r"(?i)\$\s*(\d+(?:\.\d{1,2})?).{0,80}\bpro\b",
            plain,
        )
        if near:
            return _as_price(near.group(1))
        return None
    return None


def _format_price(price):
    if price == int(price):
        return str(int(price))
    return str(price)


def extract_facts(markdown_or_html, competitor=None):
    """Return schema-validated structured facts. Instruction-like text is dropped."""
    price = extract_price(markdown_or_html)
    if price is None:
        notes = ""
    else:
        notes = "price %s" % _format_price(price)
    facts = {"price": price, "notes": notes}
    if competitor is not None:
        facts["competitor"] = html.escape(str(competitor), quote=True)
    validate_facts(facts)
    return facts


def validate_facts(facts):
    """Raise ValueError if facts violate the persona-card notes discipline."""
    if not isinstance(facts, dict):
        raise ValueError("facts must be an object")
    allowed = {"price", "notes", "competitor", "plan_count"}
    extra = set(facts) - allowed
    if extra:
        raise ValueError("facts contain keys that are not allowlisted")
    if "price" in facts:
        price = facts["price"]
        if price is not None and (
            not isinstance(price, (int, float)) or isinstance(price, bool)
        ):
            raise ValueError("price must be a number or null")
    notes = facts.get("notes", "")
    if not isinstance(notes, str):
        raise ValueError("notes must be a string")
    if _contains_instruction(notes):
        raise ValueError("notes contain instruction-like content")
    if not _NOTES_OK.match(notes):
        raise ValueError("notes are not structured facts")
    if len(notes) > 120:
        raise ValueError("notes exceed the structured-fact length cap")
    return facts


def validate_persona_card(card):
    """Raise ValueError if card does not match the persona-card schema shape."""
    if not isinstance(card, dict):
        raise ValueError("persona card must be an object")
    required = _SCHEMA.get("required", [])
    missing = [key for key in required if key not in card]
    if missing:
        raise ValueError("missing required field: %s" % ", ".join(missing))
    if not isinstance(card["competitor"], str):
        raise ValueError("competitor must be a string")
    if not isinstance(card["price"], (int, float)) or isinstance(card["price"], bool):
        raise ValueError("price must be a number")
    if not isinstance(card["pricing_url"], str):
        raise ValueError("pricing_url must be a string")
    news = card["news_urls"]
    max_items = _SCHEMA["properties"]["news_urls"].get("maxItems", 3)
    if not isinstance(news, list):
        raise ValueError("news_urls must be an array")
    if len(news) > max_items:
        raise ValueError("news_urls may have at most %s items" % max_items)
    for url in news:
        if not isinstance(url, str):
            raise ValueError("news url must be a string")
    if "notes" in card:
        if not isinstance(card["notes"], str):
            raise ValueError("notes must be a string")
        if _contains_instruction(card["notes"]):
            raise ValueError("notes contain instruction-like content")
        if not _NOTES_OK.match(card["notes"]):
            raise ValueError("notes are not structured facts")
    return card
