"""Tool router: the only path to tools, with a fixed allowlist."""

from .trace import emit

ALLOWLIST = frozenset(
    {
        "brightdata.scrape_as_markdown",
        "brightdata.search_engine",
        "sandbox.exec",
        "github.open_pr",
    }
)


class ToolRefused(Exception):
    """Raised when a tool is not on the allowlist or is not registered."""

    def __init__(self, tool_name, reason):
        self.tool_name = tool_name
        self.reason = reason
        super().__init__(reason)


class ToolRouter:
    """Dispatch only allowlisted, registered callables. Every other request is refused and traced."""

    def __init__(self, session):
        self.session = session
        self._tools = {}

    def register(self, name, fn):
        if name not in ALLOWLIST:
            raise ToolRefused(name, "that tool is not on the allowed list")
        if not callable(fn):
            raise TypeError("tool must be callable")
        self._tools[name] = fn

    def call(self, name, **kwargs):
        if name not in ALLOWLIST:
            self._refuse(name, "that tool is not on the allowed list")
        if name not in self._tools:
            self._refuse(name, "that tool is not registered")
        return self._tools[name](**kwargs)

    def _refuse(self, name, reason):
        emit(
            self.session,
            "orchestrator",
            "did",
            "refused a tool that is not allowed",
            tool=name,
            detail={"reason": reason},
        )
        raise ToolRefused(name, reason)
