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

import json
import os
import subprocess
import sys
from http.server import SimpleHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from orchestrator.session_store import SessionStore
from gate.service import GateService
from gate.repo import LocalRepoClient, GitHubRepoClient
from gate import ui as gate_ui

SESSION_DIR = ROOT / "session"


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
        store = SessionStore(str(SESSION_DIR))
        session = store.load()
        gs = GateService(session, _repo_client())
        try:
            if self.path == "/gate/allow":
                action_id = body["action_id"]
                token = gate_ui.ui_allow(session, action_id)
                result = gs.approve(action_id, token)
                payload = {"ok": True, "result": str(result)}
            elif self.path == "/gate/deny":
                gs.deny(body["action_id"], body.get("reason", "not now"))
                payload = {"ok": True, "result": "denied"}
            else:
                self.send_error(404)
                return
        except Exception as exc:
            payload = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        store.save(session)
        data = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8420
    os.chdir(ROOT)
    print(f"serving on http://localhost:{port}/ (GATE_REMOTE={os.environ.get('GATE_REMOTE', '0')})")
    HTTPServer(("127.0.0.1", port), Handler).serve_forever()
