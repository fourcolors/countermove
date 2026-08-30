"""Re-check a stored watch trigger at the start of a new session."""

import copy

from gather.extract import extract_price
from orchestrator.tool_router import ToolRouter
from orchestrator.trace import emit


def check_watch_trigger(session, client, router):
    """Re-scrape the trigger's competitor and report whether it has fired.

    The scrape goes through the tool router, never around it. The plain-
    language result event is the first event this function emits, so a
    caller that runs this before other new-session work keeps it first
    on the new run's trace.

    Returns {"fired": bool, "observed_price": number-or-None, "trigger": dict-or-None}.
    """
    if not isinstance(router, ToolRouter):
        raise TypeError(
            "check_watch_trigger requires a ToolRouter; "
            "competitor pages are never fetched around it"
        )

    trigger, decided_at = _stored_trigger(session)
    if trigger is None:
        return {"fired": False, "observed_price": None, "trigger": None, "expired": False}

    if _expired(trigger, decided_at):
        emit(session, "orchestrator", "did",
             "the watch on %s has expired (%s-day window passed); not checked"
             % (trigger["competitor"], trigger.get("window_days")),
             tool=None, detail={"trigger": copy.deepcopy(trigger), "expired": True})
        return {"fired": False, "observed_price": None,
                "trigger": copy.deepcopy(trigger), "expired": True}

    competitor = trigger["competitor"]
    threshold = float(trigger["threshold"])
    url = _competitor_url(session, competitor)

    def scrape_as_markdown(url):
        return client.scrape_as_markdown(url)

    router.register("brightdata.scrape_as_markdown", scrape_as_markdown)
    content = router.call("brightdata.scrape_as_markdown", url=url)
    if not isinstance(content, str):
        content = "" if content is None else str(content)

    observed_price = extract_price(content)
    fired = observed_price is not None and observed_price < threshold

    emit(
        session,
        "orchestrator",
        "did",
        _report_text(competitor, observed_price, threshold, fired),
        tool="brightdata.scrape_as_markdown",
        detail={
            "url": url,
            "price": observed_price,
            "threshold": threshold,
            "fired": fired,
            "competitor": competitor,
        },
    )
    return {
        "fired": fired,
        "observed_price": observed_price,
        "trigger": copy.deepcopy(trigger),
        "expired": False,
    }


def _stored_trigger(session):
    """Only the LATEST decision's trigger counts.

    A newer decision without a trigger deactivates older ones; searching
    backward for any valid trigger would resurrect stale watches.
    Returns (trigger_or_None, decided_at_iso_or_None).
    """
    if not isinstance(session, dict):
        return None, None
    items = session.get("decisions")
    if isinstance(items, list) and items:
        latest = items[-1]
        if isinstance(latest, dict):
            trigger = latest.get("watch_trigger")
            if _valid_trigger(trigger):
                return trigger, latest.get("decided_at")
    return None, None


def _expired(trigger, decided_at):
    """A trigger with a window is expired once window_days have passed
    since the persisted decision timestamp; with no timestamp or no
    window it never silently fires stale - no window means no expiry,
    but a window with a missing timestamp is treated as expired."""
    import datetime as _dt
    window = trigger.get("window_days")
    if window is None:
        return False
    if not isinstance(decided_at, str):
        return True
    try:
        decided = _dt.datetime.fromisoformat(decided_at.replace("Z", "+00:00"))
    except ValueError:
        return True
    now = _dt.datetime.now(_dt.timezone.utc)
    if decided.tzinfo is None:
        decided = decided.replace(tzinfo=_dt.timezone.utc)
    return (now - decided).days > float(window)


def _valid_trigger(trigger):
    if not isinstance(trigger, dict):
        return False
    competitor = trigger.get("competitor")
    if not isinstance(competitor, str) or not competitor.strip():
        return False
    threshold = trigger.get("threshold")
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
        return False
    try:
        float(threshold)
    except (TypeError, ValueError, OverflowError):
        return False
    return True


def _competitor_url(session, name):
    company = session.get("company") if isinstance(session, dict) else None
    if not isinstance(company, dict):
        raise ValueError("session has no company to look up %s" % name)
    for item in company.get("competitors") or []:
        if not isinstance(item, dict):
            continue
        if item.get("name") == name or item.get("competitor") == name:
            url = item.get("url") or item.get("pricing_url")
            if url:
                return url
    raise ValueError("unknown competitor: %s" % name)


def _price_display(value):
    number = float(value)
    if number == int(number):
        return str(int(number))
    return str(number)


def _report_text(competitor, observed_price, threshold, fired):
    bound = _price_display(threshold)
    if observed_price is None:
        return (
            "could not read %s's price, so the last recommendation still holds"
            % competitor
        )
    now = _price_display(observed_price)
    if fired:
        return (
            "%s is below $%s (now $%s), which would flip the last recommendation"
            % (competitor, bound, now)
        )
    return (
        "%s is still at or above $%s (now $%s), so the last recommendation still holds"
        % (competitor, bound, now)
    )
