"""Stdlib tests for the orchestrator rails (S0b)."""

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime
from pathlib import Path

import orchestrator
from orchestrator import (
    ALLOWLIST,
    LocalSubprocessSandbox,
    SandboxError,
    SessionStore,
    ToolRefused,
    ToolRouter,
    TrueForgeSandbox,
    emit,
    new_session,
)
from orchestrator.hello_world import main as hello_world_main
from orchestrator.trace import validate as validate_emitted_event

ROOT = Path(__file__).resolve().parent
SCHEMA_PATH = ROOT / "contracts" / "trace_event.schema.json"
FIXTURE_PATH = ROOT / "contracts" / "fixtures" / "trace_events.json"


def load_schema():
    with SCHEMA_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


SCHEMA = load_schema()


def validate_trace_event(event, schema=None):
    """Validate required fields and enums with plain code. No jsonschema."""
    schema = SCHEMA if schema is None else schema
    if not isinstance(event, dict):
        raise AssertionError("trace event must be an object")

    required = schema["required"]
    missing = [key for key in required if key not in event]
    if missing:
        raise AssertionError("missing required fields: %s" % ", ".join(missing))

    props = schema["properties"]

    if not isinstance(event["ts"], str) or not event["ts"]:
        raise AssertionError("ts must be a non-empty string")
    ts = event["ts"].replace("Z", "+00:00")
    try:
        datetime.fromisoformat(ts)
    except ValueError as exc:
        raise AssertionError("ts is not a date-time: %s" % event["ts"]) from exc

    if not isinstance(event["actor"], str):
        raise AssertionError("actor must be a string")

    allowed_columns = props["column"]["enum"]
    if event["column"] not in allowed_columns:
        raise AssertionError(
            "column %r is not one of %s" % (event["column"], allowed_columns)
        )

    if not isinstance(event["text"], str):
        raise AssertionError("text must be a string")

    if "tool" in event:
        tool = event["tool"]
        if tool is not None and not isinstance(tool, str):
            raise AssertionError("tool must be a string or null")

    if "detail" in event and not isinstance(event["detail"], dict):
        raise AssertionError("detail must be an object")


class TestToolRouter(unittest.TestCase):
    def test_unlisted_tool_refused_and_traced(self):
        session = new_session()
        router = ToolRouter(session)
        with self.assertRaises(ToolRefused) as ctx:
            router.call("shell.exec", command="ls")
        self.assertEqual(ctx.exception.tool_name, "shell.exec")
        self.assertTrue(session["trace"], "refusal must appear in the trace")
        event = session["trace"][-1]
        self.assertIn("refus", event["text"].lower())
        self.assertEqual(event["tool"], "shell.exec")
        self.assertEqual(event["column"], "did")
        self.assertEqual(event["actor"], "orchestrator")
        validate_trace_event(event)

    def test_unregistered_allowlisted_tool_refused_and_traced(self):
        session = new_session()
        router = ToolRouter(session)
        with self.assertRaises(ToolRefused):
            router.call("github.open_pr", title="raise Pro")
        event = session["trace"][-1]
        self.assertIn("refus", event["text"].lower())
        self.assertEqual(event["tool"], "github.open_pr")
        validate_trace_event(event)

    def test_register_non_allowlisted_refused(self):
        session = new_session()
        router = ToolRouter(session)
        with self.assertRaises(ToolRefused):
            router.register("curl.fetch", lambda url: url)
        self.assertTrue(session["trace"], "rejected registration must be traced")
        event = session["trace"][-1]
        self.assertIn("refus", event["text"].lower())
        self.assertEqual(event["tool"], "curl.fetch")
        self.assertEqual(event["column"], "did")
        self.assertEqual(event["actor"], "orchestrator")
        validate_trace_event(event)

    def test_direct_bypass_impossible_via_public_surface(self):
        dispatched = []
        original = ToolRouter.call

        def tracking_call(self, name, **kwargs):
            dispatched.append(name)
            return original(self, name, **kwargs)

        ToolRouter.call = tracking_call
        try:
            stdout = io.StringIO()
            with tempfile.TemporaryDirectory() as tmp:
                with redirect_stdout(stdout), redirect_stderr(io.StringIO()):
                    hello_world_main(tmp)
        finally:
            ToolRouter.call = original

        self.assertIn("sandbox.exec", dispatched)
        self.assertIn("brightdata.scrape_as_markdown", dispatched)

        for name in ("call", "exec", "run_tool", "invoke"):
            self.assertFalse(
                hasattr(orchestrator, name),
                "public surface must not expose %s as a router bypass" % name,
            )

    def test_registered_allowlisted_tool_runs(self):
        session = new_session()
        router = ToolRouter(session)
        router.register("brightdata.search_engine", lambda query: {"hits": [query]})
        result = router.call("brightdata.search_engine", query="Rival A")
        self.assertEqual(result, {"hits": ["Rival A"]})
        self.assertEqual(
            ALLOWLIST,
            {
                "brightdata.scrape_as_markdown",
                "brightdata.search_engine",
                "sandbox.exec",
                "github.open_pr",
            },
        )


class TestTrace(unittest.TestCase):
    def test_every_emitted_event_validates_against_schema(self):
        session = new_session()
        emit(session, "orchestrator", "doing", "checking Rival A's pricing page")
        emit(session, "orchestrator", "waiting", "waiting for your approval")
        emit(
            session,
            "orchestrator",
            "did",
            "checked Rival A's pricing page",
            tool="brightdata.scrape_as_markdown",
            detail={"url": "https://rival-a.example/pricing", "price": 45},
        )
        router = ToolRouter(session)
        with self.assertRaises(ToolRefused):
            router.call("not.a.tool")
        for event in session["trace"]:
            validate_trace_event(event)

    def test_fixture_events_validate(self):
        with FIXTURE_PATH.open(encoding="utf-8") as handle:
            events = json.load(handle)
        self.assertTrue(events)
        for event in events:
            validate_trace_event(event)

    def test_reject_bad_column(self):
        session = new_session()
        with self.assertRaises(ValueError):
            emit(session, "orchestrator", "maybe", "not a real column")

    def test_reject_missing_required_field(self):
        with self.assertRaises(ValueError):
            validate_emitted_event(
                {
                    "actor": "orchestrator",
                    "column": "did",
                    "text": "checked Rival A's pricing page",
                }
            )

    def test_reject_date_only_ts(self):
        with self.assertRaises(ValueError):
            validate_emitted_event(
                {
                    "ts": "2026-08-29",
                    "actor": "orchestrator",
                    "column": "did",
                    "text": "checked Rival A's pricing page",
                }
            )

    def test_reject_wrong_type_detail(self):
        session = new_session()
        with self.assertRaises(ValueError):
            emit(
                session,
                "orchestrator",
                "did",
                "checked Rival A's pricing page",
                detail="not an object",
            )

    def test_stored_event_is_immutable_snapshot(self):
        session = new_session()
        detail = {
            "url": "https://rival-a.example/pricing",
            "nested": {"price": 45},
        }
        emit(
            session,
            "orchestrator",
            "did",
            "checked Rival A's pricing page",
            tool="brightdata.scrape_as_markdown",
            detail=detail,
        )
        detail["url"] = "mutated"
        detail["nested"]["price"] = 0
        stored = session["trace"][-1]
        self.assertEqual(stored["detail"]["url"], "https://rival-a.example/pricing")
        self.assertEqual(stored["detail"]["nested"]["price"], 45)


class TestSessionStore(unittest.TestCase):
    def test_round_trip(self):
        session = new_session()
        session["company"] = {"name": "Acme Stay"}
        session["move"] = {"plan": "pro", "from": 49, "to": 59}
        session["tree"] = {"id": "root", "children": []}
        session["decisions"] = [{"action": "deny", "reason": "not now"}]
        session["snapshots"] = [{"url": "https://rival-a.example/pricing", "digest": "abc"}]
        emit(
            session,
            "orchestrator",
            "did",
            "checked Rival A's pricing page",
            tool="brightdata.scrape_as_markdown",
            detail={"price": 45},
        )
        with tempfile.TemporaryDirectory() as tmp:
            store = SessionStore(tmp)
            store.save(session)
            loaded = store.load()
        self.assertEqual(loaded["company"], session["company"])
        self.assertEqual(loaded["move"], session["move"])
        self.assertEqual(loaded["tree"], session["tree"])
        self.assertEqual(loaded["decisions"], session["decisions"])
        self.assertEqual(loaded["snapshots"], session["snapshots"])
        self.assertEqual(len(loaded["trace"]), 1)
        validate_trace_event(loaded["trace"][0])
        self.assertEqual(loaded["trace"][0]["text"], session["trace"][0]["text"])

    def test_load_missing_returns_fresh_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing_dir = SessionStore(Path(tmp) / "does-not-exist")
            from_missing_dir = missing_dir.load()
            existing_dir = SessionStore(tmp)
            from_missing_file = existing_dir.load()
        self.assertEqual(from_missing_dir, new_session())
        self.assertEqual(from_missing_file, new_session())


class TestSandbox(unittest.TestCase):
    def test_runs_trivial_script_and_traces(self):
        session = new_session()
        box = LocalSubprocessSandbox(session, timeout=10)
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "echo.py"
            script.write_text(
                "import json, sys\n"
                "data = json.load(sys.stdin)\n"
                "json.dump({'sum': data['a'] + data['b']}, sys.stdout)\n",
                encoding="utf-8",
            )
            output = box.run(str(script), {"a": 2, "b": 3})
        self.assertEqual(output, {"sum": 5})
        self.assertTrue(session["trace"], "sandbox run must appear in the trace")
        event = session["trace"][-1]
        self.assertEqual(event["tool"], "sandbox.exec")
        self.assertEqual(event["detail"]["inputs"], {"a": 2, "b": 3})
        self.assertEqual(event["detail"]["outputs"], {"sum": 5})
        validate_trace_event(event)

    def test_trueforge_stub_raises(self):
        session = new_session()
        box = TrueForgeSandbox(session)
        with self.assertRaises(NotImplementedError) as ctx:
            box.run("score.py", {"leaf": 1})
        self.assertIn("adapter seam", str(ctx.exception).lower())
        self.assertTrue(session["trace"])
        validate_trace_event(session["trace"][-1])

    def test_nonzero_exit_is_traced(self):
        session = new_session()
        box = LocalSubprocessSandbox(session, timeout=10)
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "fail.py"
            script.write_text("import sys\nsys.exit(2)\n", encoding="utf-8")
            with self.assertRaises(SandboxError):
                box.run(str(script), {})
        event = session["trace"][-1]
        self.assertIn("error", event["detail"])
        validate_trace_event(event)


class TestHelloWorld(unittest.TestCase):
    def test_hello_world_end_to_end(self):
        stdout = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            with redirect_stdout(stdout), redirect_stderr(io.StringIO()):
                session = hello_world_main(tmp)
            stored = SessionStore(tmp).load()
        printed = json.loads(stdout.getvalue())
        self.assertEqual(printed, session["trace"])
        self.assertEqual(stored["company"]["name"], "Acme Stay")
        self.assertTrue(stored["trace"])
        self.assertEqual(stored["trace"], session["trace"])

        tools = {event.get("tool") for event in session["trace"]}
        self.assertIn("brightdata.scrape_as_markdown", tools)
        self.assertIn("sandbox.exec", tools)

        texts = " ".join(event["text"].lower() for event in session["trace"])
        self.assertIn("pricing page", texts)
        self.assertIn("sandbox", texts)

        sandbox_events = [
            event
            for event in session["trace"]
            if event.get("tool") == "sandbox.exec"
        ]
        self.assertTrue(sandbox_events)
        self.assertEqual(sandbox_events[-1]["detail"]["inputs"], {"hello": "world"})
        self.assertEqual(
            sandbox_events[-1]["detail"]["outputs"],
            {"ok": True, "echo": {"hello": "world"}},
        )

        for event in session["trace"]:
            validate_trace_event(event)

    def test_hello_world_module_prints_trace(self):
        with tempfile.TemporaryDirectory() as tmp:
            completed = subprocess.run(
                [sys.executable, "-m", "orchestrator.hello_world", tmp],
                cwd=str(ROOT),
                capture_output=True,
                text=True,
                timeout=20,
                env=dict(os.environ),
            )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        printed = json.loads(completed.stdout)
        self.assertIsInstance(printed, list)
        self.assertTrue(printed)
        for event in printed:
            validate_trace_event(event)


if __name__ == "__main__":
    unittest.main()
