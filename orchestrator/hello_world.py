"""Hello-world: one fake scrape through the router, one sandbox run, session on disk, print the trace."""

import json
import sys
import tempfile
from pathlib import Path

from .sandbox import LocalSubprocessSandbox
from .session_store import SessionStore, new_session
from .tool_router import ToolRouter
from .trace import emit

_ECHO_SCRIPT = """\
import json
import sys

data = json.load(sys.stdin)
json.dump({"ok": True, "echo": data}, sys.stdout)
"""


def _fake_scrape(url):
    return {
        "url": url,
        "markdown": "Rival A lists Pro at $45 a month.",
        "price": 45,
    }


def main(session_dir=None):
    if session_dir is None:
        session_dir = tempfile.mkdtemp(prefix="countermove-session-")
    session_dir = str(session_dir)

    session = new_session()
    session["company"] = {"name": "Acme Stay"}
    session["move"] = {"plan": "pro", "from": 49, "to": 59}

    router = ToolRouter(session)
    sandbox = LocalSubprocessSandbox(session, timeout=10)
    store = SessionStore(session_dir)

    router.register("brightdata.scrape_as_markdown", _fake_scrape)

    emit(
        session,
        "orchestrator",
        "doing",
        "checking Rival A's pricing page",
        tool="brightdata.scrape_as_markdown",
        detail={"url": "https://rival-a.example/pricing"},
    )
    scrape = router.call(
        "brightdata.scrape_as_markdown",
        url="https://rival-a.example/pricing",
    )
    emit(
        session,
        "orchestrator",
        "did",
        "checked Rival A's pricing page",
        tool="brightdata.scrape_as_markdown",
        detail={"url": scrape["url"], "price": scrape["price"]},
    )

    script_path = Path(session_dir) / "echo.py"
    script_path.write_text(_ECHO_SCRIPT, encoding="utf-8")
    sandbox.run(str(script_path), {"hello": "world"})

    store.save(session)

    print(json.dumps(session["trace"], indent=2))
    print("session written to %s" % store.path, file=sys.stderr)
    return session


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else None
    main(target)
