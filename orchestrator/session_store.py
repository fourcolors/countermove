"""Load and save a session as JSON on disk. Writes are atomic (temp file + rename)."""

import json
import os
import tempfile
from pathlib import Path

SESSION_FILENAME = "session.json"
SESSION_KEYS = ("company", "move", "tree", "decisions", "trace", "snapshots")


def new_session():
    return {
        "company": None,
        "move": None,
        "tree": None,
        "decisions": [],
        "trace": [],
        "snapshots": [],
    }


class SessionStore:
    def __init__(self, dir_path):
        self.dir_path = Path(dir_path)

    @property
    def path(self):
        return self.dir_path / SESSION_FILENAME

    def save(self, session):
        self.dir_path.mkdir(parents=True, exist_ok=True)
        payload = {key: session.get(key) for key in SESSION_KEYS}
        fd, tmp_name = tempfile.mkstemp(
            prefix=".session.",
            suffix=".tmp",
            dir=str(self.dir_path),
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, self.path)
        except Exception:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise

    def load(self):
        with self.path.open(encoding="utf-8") as handle:
            data = json.load(handle)
        session = new_session()
        for key in SESSION_KEYS:
            if key in data:
                session[key] = data[key]
        return session
