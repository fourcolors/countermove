"""Structured-fact extraction for untrusted scraped pages.

Price comes out as a number or None, never raw text.
Facts are schema-shaped and drop instruction-like content.
"""

import html
import json
import math
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

# Visible-text price: optional thousands separators, at most two decimals.
_PRICE_NUM = r"((?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{1,2})?)"
_DOLLAR_PRICE = re.compile(r"\$\s*" + _PRICE_NUM)
_PRO_PRICE = re.compile(
    r"(?is)\bpro\b.{0,160}?\$\s*" + _PRICE_NUM
)
_PRO_PRICE_AFTER = re.compile(
    r"(?is)\$\s*" + _PRICE_NUM + r".{0,80}\bpro\b"
)
_NOTES_OK = re.compile(
    r"^(?:price (?:unknown|\d+(?:\.\d+)?)(?:; plan count \d+)?)?$"
)
_MIN_PRICE = 0
_MAX_PRICE = 100000


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


def _strip_script_and_style(text):
    """Drop script/style blocks, including unclosed ones (consume to EOF)."""
    cleaned = re.sub(r"<!--.*?-->", " ", text, flags=re.DOTALL)
    cleaned = re.sub(
        r"(?is)<script\b[^>]*>.*?(?:</script\s*>|$)",
        " ",
        cleaned,
    )
    cleaned = re.sub(
        r"(?is)<style\b[^>]*>.*?(?:</style\s*>|$)",
        " ",
        cleaned,
    )
    return cleaned


def _to_visible_text(markdown_or_html):
    """Strip script/style and tags to visible text.

    Returns None when a script/style block is malformed (fail closed).
    """
    cleaned = _strip_script_and_style(markdown_or_html)
    if re.search(r"(?is)<(script|style)\b", cleaned):
        return None
    cleaned = re.sub(
        r"(?is)<(?P<tag>[a-z][a-z0-9]*)\b[^>]*\bhidden\b[^>]*>.*?(?:</(?P=tag)\s*>|$)",
        " ",
        cleaned,
    )
    plain = re.sub(r"<[^>]+>", " ", cleaned)
    plain = html.unescape(plain)
    return re.sub(r"\s+", " ", plain).strip()


def _as_price(raw):
    """Parse a numeric price; reject non-finite, non-positive, and absurd values."""
    if raw is None:
        return None
    try:
        text = str(raw).replace(",", "")
        value = float(text)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(value):
        return None
    if not (_MIN_PRICE < value < _MAX_PRICE):
        return None
    return value


def extract_price(markdown_or_html):
    """Return a price as float, or None when nothing parseable is present.

    Matching runs on visible text only, after script/style and tags are stripped.
    Malformed script/style blocks fail closed (None).
    """
    if not isinstance(markdown_or_html, str) or not markdown_or_html.strip():
        return None
    visible = _to_visible_text(markdown_or_html)
    if not visible:
        return None
    match = _PRO_PRICE.search(visible)
    if match:
        value = _as_price(match.group(1))
        if value is not None:
            return value
    match = _PRO_PRICE_AFTER.search(visible)
    if match:
        value = _as_price(match.group(1))
        if value is not None:
            return value
    found = []
    for raw in _DOLLAR_PRICE.findall(visible):
        value = _as_price(raw)
        if value is not None:
            found.append(value)
    if len(found) == 1:
        return found[0]
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
