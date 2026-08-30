#!/usr/bin/env python3
"""Serve the Countermove UI over the live session with working gate buttons.

GET  /                      -> ui/index.html (static)
GET  /session/session.json  -> the live session
POST /gate/allow            -> ui_allow + GateService.approve -> PR url
POST /gate/deny             -> GateService.deny(reason)

The approve path uses GitHubRepoClient against fourcolors/acme-stay-pricing
when GATE_REMOTE=1; otherwise a LocalRepoClient sandbox checkout under
session/local-pricing (safe default for rehearsal).
"""

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from orchestrator.session_store import SessionStore
from gate.service import GateService
from gate.repo import LocalRepoClient, GitHubRepoClient
from gate import ui as gate_ui
from bootstrap.move_parse import Rejection
import run_demo

SESSION_DIR = ROOT / "session"
_PIPELINE_LOCK = threading.Lock()


class DemoServer(ThreadingHTTPServer):
    """Concurrent GETs stay live while a /run normalize is in flight."""

    daemon_threads = True


def make_server(host="127.0.0.1", port=8420):
    return DemoServer((host, port), Handler)


def payload_for_run(returned, stdout_text):
    """Build the /run JSON body. Failures expose only the friendly reply."""
    if isinstance(returned, Rejection):
        reply = returned.reply or "the simulation did not finish"
        return {"ok": False, "result": None, "error": reply, "reply": reply}
    ran = "pending:" in (stdout_text or "")
    return {
        "ok": ran,
        "result": stdout_text if ran else None,
        "error": None if ran else (stdout_text or "the simulation did not finish"),
    }


def _repo_client():
    if os.environ.get("GATE_REMOTE") == "1":
        return GitHubRepoClient("fourcolors/acme-stay-pricing")
    local = SESSION_DIR / "local-pricing"
    if not (local / ".git").exists():
        local.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=local, check=True)
        (local / "pricing.yaml").write_text("plan: pro\nprice: 49\n")
        subprocess.run(["git", "add", "-A"], cwd=local, check=True)
        subprocess.run(["git", "-c", "user.email=demo@countermove", "-c", "user.name=demo",
                        "commit", "-qm", "seed"], cwd=local, check=True)
    return LocalRepoClient(str(local))


class Handler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self.send_response(302)
            self.send_header("Location", "/ui/")
            self.end_headers()
            return
        return super().do_GET()

    ALLOWED_ORIGINS = {"http://localhost:8420", "http://127.0.0.1:8420"}

    def _reject(self, code, message):
        data = json.dumps({"ok": False, "error": message}).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_json(self, payload, code=200):
        data = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _run_pipeline(self, body):
        sentence = str(body.get("sentence", "")).strip()
        if not sentence:
            self._reject(400, "type a move first")
            return
        shutil.rmtree(SESSION_DIR, ignore_errors=True)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            returned = run_demo.main(sentence)
        # run_demo wrote the fresh session itself; do not save a stale object over it.
        self._send_json(payload_for_run(returned, out.getvalue().strip()))

    def _gate_pipeline(self, body):
        store = SessionStore(str(SESSION_DIR))
        session = store.load()
        gs = GateService(session, _repo_client())
        try:
            if self.path == "/gate/allow":
                action_id = body["action_id"]
                token = gate_ui.ui_allow(session, action_id)
                result = gs.approve(action_id, token)
                payload = {"ok": True, "result": str(result)}
            else:
                gs.deny(body["action_id"], body.get("reason", "not now"))
                payload = {"ok": True, "result": "denied"}
        except Exception as exc:
            payload = {"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)}
        store.save(session)
        self._send_json(payload)

    def do_POST(self):
        # The gate endpoint accepts only same-origin browser JSON posts:
        # a cross-origin page cannot mint-and-consume an approval in one shot.
        origin = self.headers.get("Origin", "")
        if origin not in self.ALLOWED_ORIGINS:
            self._reject(403, "gate requests must come from the Countermove page itself")
            return
        if not (self.headers.get("Content-Type", "").startswith("application/json")):
            self._reject(415, "gate requests must be application/json")
            return
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        if self.path == "/run":
            with _PIPELINE_LOCK:
                self._run_pipeline(body)
            return
        if self.path in ("/gate/allow", "/gate/deny"):
            with _PIPELINE_LOCK:
                self._gate_pipeline(body)
            return
        self.send_error(404)

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8420
    os.chdir(ROOT)
    print(f"serving on http://localhost:{port}/ (GATE_REMOTE={os.environ.get('GATE_REMOTE', '0')})")
    make_server("127.0.0.1", port).serve_forever()
