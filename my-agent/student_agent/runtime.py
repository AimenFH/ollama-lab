"""Tool registry and permission boundary."""

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

MAX_ARG_CHARS = 12_000


class ToolDenied(Exception):
    """The request is outside what this runtime permits."""


class ToolError(Exception):
    """The request was permitted but could not be completed."""


def list_files(runtime):
    raise NotImplementedError("list_files arrives in Checkpoint 3")


def read_file(runtime, path):
    raise NotImplementedError("read_file arrives in Checkpoint 3")


def search_files(runtime, query):
    raise NotImplementedError("search_files arrives in Checkpoint 3")


def write_file(runtime, path, content):
    raise NotImplementedError("write_file arrives in Checkpoint 3")


def edit_file(runtime, path, old, new):
    raise NotImplementedError("edit_file arrives in Checkpoint 3")


def fetch_url(runtime, url):
    raise NotImplementedError("fetch_url arrives in Checkpoint 3")


def bash(runtime, command):
    raise NotImplementedError("bash arrives in Checkpoint 3")


@dataclass(frozen=True)
class Tool:
    description: str
    args: tuple
    capability: str
    function: Callable


REGISTRY = {
    "list_files": Tool("List up to 200 workspace file paths.", (), "read", list_files),
    "read_file": Tool("Read a UTF-8 text file (up to 12,000 characters).", ("path",), "read", read_file),
    "search_files": Tool(
        "Find literal text; returns path, line number, and excerpt.", ("query",), "read", search_files
    ),
    "write_file": Tool(
        "Create a new file. Fails if the file already exists.", ("path", "content"), "write", write_file
    ),
    "edit_file": Tool(
        "Replace text `old` with `new`; `old` must occur exactly once.", ("path", "old", "new"), "write", edit_file
    ),
    "fetch_url": Tool(
        "Read approved HTTPS documentation from docs.python.org.", ("url",), "fetch", fetch_url
    ),
    "bash": Tool(
        "Run a local bash command in the workspace after the user approves it.", ("command",), "bash", bash
    ),
}

MODE_CAPABILITIES = {
    "read-only": frozenset({"read", "fetch"}),
    "edit": frozenset({"read", "fetch", "write", "bash"}),
}


class Runtime:
    """Validate and execute model-requested tools inside a workspace."""

    def __init__(
        self,
        root,
        mode="read-only",
        enabled=None,
        approve=None,
        offline=False,
    ):
        if mode not in MODE_CAPABILITIES:
            raise ValueError(f"unknown mode {mode!r}; choose from {sorted(MODE_CAPABILITIES)}")
        enabled = set(REGISTRY if enabled is None else enabled)
        unknown = enabled - set(REGISTRY)
        if unknown:
            raise ValueError(f"unknown tools {sorted(unknown)}; choose from {sorted(REGISTRY)}")
        self.root = Path(root).resolve()
        self.mode = mode
        self.enabled = enabled
        self.approve = approve or (lambda _command, _cwd: False)
        self.offline = offline

    def allows(self, name):
        return name in self.enabled and REGISTRY[name].capability in MODE_CAPABILITIES[self.mode]

    def describe_tools(self):
        return [
            {"name": name, "description": tool.description, "args": list(tool.args)}
            for name, tool in REGISTRY.items()
            if self.allows(name)
        ]

    def execute(self, action):
        """Validate one action, enforce policy, and return a result object."""
        if not isinstance(action, dict) or set(action) != {"tool", "args"}:
            return _error('an action must be an object with exactly "tool" and "args"')
        name, args = action["tool"], action["args"]
        if not isinstance(name, str) or name not in REGISTRY:
            return _error(f"unknown tool {name!r}; known tools: {sorted(REGISTRY)}")
        tool = REGISTRY[name]

        if name not in self.enabled:
            return _denied(f"{name} is not enabled for this run")
        if tool.capability not in MODE_CAPABILITIES[self.mode]:
            return _denied(f"{name} is not permitted in {self.mode} mode")

        if not isinstance(args, dict) or set(args) != set(tool.args):
            return _error(f"{name} takes exactly these arguments: {list(tool.args)}")
        for key, value in args.items():
            if not isinstance(value, str):
                return _error(f"argument {key!r} must be a string")
            if len(value) > MAX_ARG_CHARS:
                return _error(f"argument {key!r} exceeds {MAX_ARG_CHARS} characters")

        if tool.capability == "bash" and not self._approved(args["command"]):
            return _denied("the user did not approve this command")

        try:
            return {"status": "ok", "output": tool.function(self, **args)}
        except ToolDenied as exc:
            return _denied(str(exc))
        except ToolError as exc:
            return _error(str(exc))
        except Exception as exc:
            return _error(f"{type(exc).__name__}: {exc}")

    def _approved(self, command):
        try:
            return self.approve(command, str(self.root)) is True
        except Exception:
            return False


def _error(message):
    return {"status": "error", "output": message}


def _denied(message):
    return {"status": "denied", "output": message}
