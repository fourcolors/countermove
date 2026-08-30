"""Sandbox seam: local subprocess stand-in, plus a TrueForge adapter stub."""

import json
import subprocess
from abc import ABC, abstractmethod

from .trace import emit


class SandboxError(Exception):
    """A sandbox run failed, timed out, or did not return JSON."""


class Sandbox(ABC):
    """Run a script with JSON in, JSON out."""

    @abstractmethod
    def run(self, script_path, input_json):
        """Execute script_path with input_json; return output_json."""


class LocalSubprocessSandbox(Sandbox):
    """Local stand-in: python3 subprocess with a timeout."""

    def __init__(self, session, timeout=30):
        self.session = session
        self.timeout = timeout

    def run(self, script_path, input_json):
        script = str(script_path)
        payload = {} if input_json is None else input_json
        error = None
        output_json = None
        try:
            completed = subprocess.run(
                ["python3", script],
                input=json.dumps(payload),
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
        except subprocess.TimeoutExpired:
            error = "timed out"
            self._trace(script, payload, None, error)
            raise SandboxError("sandbox run timed out") from None

        if completed.returncode != 0:
            error = completed.stderr.strip() or ("exit %s" % completed.returncode)
            self._trace(script, payload, None, error)
            raise SandboxError(error)

        raw = completed.stdout.strip()
        if not raw:
            output_json = {}
        else:
            try:
                output_json = json.loads(raw)
            except json.JSONDecodeError as exc:
                error = "sandbox script did not print JSON"
                self._trace(script, payload, None, error)
                raise SandboxError(error) from exc

        self._trace(script, payload, output_json, None)
        return output_json

    def _trace(self, script, inputs, outputs, error):
        detail = {"inputs": inputs, "outputs": outputs, "script": script}
        if error is not None:
            detail["error"] = error
        emit(
            self.session,
            "orchestrator",
            "did",
            "ran a sandbox script",
            tool="sandbox.exec",
            detail=detail,
        )


class TrueForgeSandbox(Sandbox):
    """Adapter seam for TrueForge sandbox exec.

    Swap this class in for LocalSubprocessSandbox when the orchestrator
    runs on TrueForge. Wire the TrueForge sandbox-exec client in run().
    """

    def __init__(self, session, timeout=30):
        self.session = session
        self.timeout = timeout

    def run(self, script_path, input_json):
        emit(
            self.session,
            "orchestrator",
            "did",
            "sandbox is not wired to TrueForge yet",
            tool="sandbox.exec",
            detail={
                "inputs": input_json,
                "outputs": None,
                "script": str(script_path),
            },
        )
        # Adapter seam: replace this stub with the TrueForge sandbox exec client.
        raise NotImplementedError(
            "TrueForgeSandbox is the adapter seam for TrueForge sandbox exec"
        )
