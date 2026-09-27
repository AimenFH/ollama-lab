"""Tool registry and permission boundary."""

import os
import selectors
import signal
import stat
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

MAX_ARG_CHARS = 12_000
MAX_READ_CHARS = 12_000
MAX_EDIT_BYTES = 12_000
MAX_LIST_FILES = 200
MAX_SEARCH_FILES = 200
MAX_MATCHES = 50
MAX_EXCERPT_CHARS = 160
MAX_SEARCH_FILE_BYTES = 1_000_000
SKIPPED_DIRS = frozenset({"__pycache__"})

# Course-owned files: readable, never created, edited, or overwritten.
PROTECTED_FILES = frozenset({
    "orders/validation.py",
    "tests/test_acceptance.py",
    "docs/business-rules.md",
})

FETCH_HOST = "docs.python.org"
FETCH_TIMEOUT = 10
MAX_FETCH_BYTES = 12_000
# Plain documentation paths only, so workspace text cannot be smuggled out in a URL.
FETCH_PATH_CHARS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789/._-")
MAX_FETCH_PATH_CHARS = 200
DEFAULT_FIXTURES_DIR = Path(__file__).resolve().parents[2] / "fixtures"
OFFLINE_FIXTURES = {"https://docs.python.org/3/library/decimal.html": "decimal-offline.txt"}

BASH_TIMEOUT = 20
MAX_BASH_OUTPUT = 12_000
BASH_ENV_KEYS = ("PATH", "HOME", "LANG", "TMPDIR")


class ToolDenied(Exception):
    """The request is outside what this runtime permits."""


class ToolError(Exception):
    """The request was permitted but could not be completed."""


# --- Workspace boundary -------------------------------------------------------


def _is_hidden(parts):
    return any(part.startswith(".") for part in parts)


def _is_protected(root, relative, target):
    # Compare names case-insensitively (macOS) and by inode (links to the same file).
    if relative.casefold() in {name.casefold() for name in PROTECTED_FILES}:
        return True
    for name in PROTECTED_FILES:
        original = root / name
        try:
            if target.exists() and original.exists() and os.path.samefile(target, original):
                return True
        except OSError:
            return True
    return False


def resolve_path(runtime, path, write=False):
    """Return (absolute target, workspace-relative name) or raise ToolDenied/ToolError."""
    if not path or "\x00" in path:
        raise ToolError("path must be a non-empty relative path")
    requested = Path(path)
    if requested.is_absolute():
        raise ToolDenied(f"absolute paths are not allowed: {path}")
    if ".." in requested.parts:
        raise ToolDenied(f"'..' is not allowed in paths: {path}")
    if _is_hidden(requested.parts):
        raise ToolDenied(f"hidden paths are not allowed: {path}")
    try:
        target = (runtime.root / requested).resolve()
    except (OSError, RuntimeError) as exc:
        raise ToolError(f"cannot resolve {path}: {exc}") from None
    try:
        relative = target.relative_to(runtime.root)
    except ValueError:
        raise ToolDenied(f"{path} resolves outside the workspace") from None
    if _is_hidden(relative.parts):
        raise ToolDenied(f"{path} resolves to a hidden path")
    name = relative.as_posix()
    if write and _is_protected(runtime.root, name, target):
        raise ToolDenied(f"{name} is a course-owned file and cannot be changed")
    return target, name


def _workspace_files(root, limit):
    """Return up to `limit` regular files, sorted, without following links."""
    found = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = sorted(
            d for d in dirnames
            if not d.startswith(".") and d not in SKIPPED_DIRS
            and not os.path.islink(os.path.join(dirpath, d))
        )
        for filename in sorted(filenames):
            full = os.path.join(dirpath, filename)
            if filename.startswith(".") or not stat.S_ISREG(os.lstat(full).st_mode):
                continue
            if len(found) == limit:
                return found, True
            found.append(Path(full).relative_to(root).as_posix())
    return found, False


def _text_or_none(path):
    """Return UTF-8 text, or None for binary, undecodable, or oversized files."""
    try:
        if path.stat().st_size > MAX_SEARCH_FILE_BYTES:
            return None
        raw = path.read_bytes()
    except OSError:
        return None
    if b"\x00" in raw:
        return None
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _excerpt(line, query):
    line = line.strip()
    if len(line) <= MAX_EXCERPT_CHARS:
        return line
    start = max(0, line.find(query) - MAX_EXCERPT_CHARS // 4)
    return line[start:start + MAX_EXCERPT_CHARS] + "..."


# --- File tools ---------------------------------------------------------------


def list_files(runtime):
    files, more = _workspace_files(runtime.root, MAX_LIST_FILES)
    result = {"files": files, "truncated": more}
    if more:
        result["note"] = f"only the first {MAX_LIST_FILES} files are listed"
    return result


def read_file(runtime, path):
    target, name = resolve_path(runtime, path)
    if not target.is_file():
        raise ToolError(f"{name} is not an existing file")
    try:
        with open(target, encoding="utf-8", newline="") as handle:
            text = handle.read(MAX_READ_CHARS + 1)
    except UnicodeDecodeError:
        raise ToolError(f"{name} is not UTF-8 text") from None
    if "\x00" in text:
        raise ToolError(f"{name} looks like a binary file")
    result = {"path": name, "content": text[:MAX_READ_CHARS], "truncated": len(text) > MAX_READ_CHARS}
    if result["truncated"]:
        result["note"] = f"file is longer; only the first {MAX_READ_CHARS} characters are shown"
    return result


def search_files(runtime, query):
    if not query.strip() or "\n" in query:
        raise ToolError("query must be non-empty text on a single line")
    files, more_files = _workspace_files(runtime.root, MAX_SEARCH_FILES)
    matches = []
    for name in files:
        text = _text_or_none(runtime.root / name)
        if text is None:
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            if query not in line:
                continue
            if len(matches) == MAX_MATCHES:
                return {"matches": matches, "match_limit_reached": True, "file_limit_reached": more_files}
            matches.append({"path": name, "line": number, "excerpt": _excerpt(line, query)})
    return {"matches": matches, "match_limit_reached": False, "file_limit_reached": more_files}


def write_file(runtime, path, content):
    target, name = resolve_path(runtime, path, write=True)
    data = content.encode("utf-8")
    if len(data) > MAX_EDIT_BYTES:
        raise ToolError(f"content is {len(data)} bytes; the limit is {MAX_EDIT_BYTES}")
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(target, "xb") as handle:
            handle.write(data)
    except FileExistsError:
        raise ToolError(f"{name} already exists; use edit_file to change it") from None
    return f"created {name} ({len(data)} bytes)"


def edit_file(runtime, path, old, new):
    target, name = resolve_path(runtime, path, write=True)
    if not old:
        raise ToolError("old text must not be empty")
    if not target.is_file():
        raise ToolError(f"{name} is not an existing file")
    if target.stat().st_size > MAX_EDIT_BYTES:
        raise ToolError(f"{name} is larger than {MAX_EDIT_BYTES} bytes; exact edits are not allowed")
    try:
        text = target.read_bytes().decode("utf-8")
    except UnicodeDecodeError:
        raise ToolError(f"{name} is not UTF-8 text") from None
    count = text.count(old)
    if count == 0:
        raise ToolError(f"old text not found in {name}; read the file and copy the exact text")
    if count > 1:
        raise ToolError(f"old text occurs {count} times in {name}; include more context so it occurs once")
    updated = text.replace(old, new, 1).encode("utf-8")
    if len(updated) > MAX_EDIT_BYTES:
        raise ToolError(f"the edited file would be {len(updated)} bytes; the limit is {MAX_EDIT_BYTES}")
    target.write_bytes(updated)
    return f"replaced 1 occurrence in {name}"


# --- Documentation tool -------------------------------------------------------


class _RejectRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # urllib then raises HTTPError with the 3xx code


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.skipping = 0
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skipping += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self.skipping:
            self.skipping -= 1

    def handle_data(self, data):
        if not self.skipping and data.strip():
            self.parts.append(data.strip())


def check_url(url):
    """Allow only plain HTTPS documentation URLs on docs.python.org."""
    if any(not ch.isprintable() or ch.isspace() for ch in url) or "\\" in url:
        raise ToolDenied("the URL contains whitespace, control characters, or backslashes")
    parts = urlsplit(url)
    if parts.scheme != "https":
        raise ToolDenied("only https URLs are allowed")
    if "@" in parts.netloc:
        raise ToolDenied("URLs with a username or password are not allowed")
    try:
        port = parts.port
    except ValueError:
        raise ToolDenied("the URL has an invalid port") from None
    if parts.hostname != FETCH_HOST or port not in (None, 443):
        raise ToolDenied(f"only {FETCH_HOST} on the default HTTPS port is approved")
    if "?" in url or "#" in url:
        raise ToolDenied("URLs with a query or fragment are not allowed")
    if len(parts.path) > MAX_FETCH_PATH_CHARS or not set(parts.path) <= FETCH_PATH_CHARS:
        raise ToolDenied("the URL path must be a plain documentation path")


def fetch_url(runtime, url):
    check_url(url)
    if runtime.offline:
        fixture = OFFLINE_FIXTURES.get(url)
        if fixture is None:
            raise ToolError(f"offline mode has no fixture for {url}; available: {sorted(OFFLINE_FIXTURES)}")
        return {
            "url": url,
            "source": "offline fixture",
            "content": (runtime.fixtures_dir / fixture).read_text(encoding="utf-8"),
            "truncated": False,
            "note": "offline fixture, not a live response from docs.python.org",
        }

    request = urllib.request.Request(
        url, headers={"User-Agent": "week1-student-agent", "Accept": "text/html, text/plain"}, method="GET"
    )
    try:
        with runtime.fetch_opener.open(request, timeout=FETCH_TIMEOUT) as response:
            content_type = response.headers.get_content_type()
            if not content_type.startswith("text/"):
                raise ToolError(f"{url} returned {content_type}; only text or HTML is accepted")
            charset = response.headers.get_content_charset() or "utf-8"
            raw = response.read(MAX_FETCH_BYTES + 1)
    except urllib.error.HTTPError as exc:
        if 300 <= exc.code < 400:
            raise ToolError(f"redirect rejected: {url} redirects to {exc.headers.get('Location')}") from None
        raise ToolError(f"{url} returned HTTP {exc.code}") from None
    except (OSError, ValueError) as exc:
        raise ToolError(f"network error fetching {url}: {exc}") from None

    truncated = len(raw) > MAX_FETCH_BYTES
    try:
        text = raw[:MAX_FETCH_BYTES].decode(charset, "replace")
    except LookupError:
        text = raw[:MAX_FETCH_BYTES].decode("utf-8", "replace")
    if content_type == "text/html":
        extractor = _TextExtractor()
        extractor.feed(text)
        text = " ".join(extractor.parts)
    result = {"url": url, "source": "live docs.python.org response", "content": text, "truncated": truncated}
    if truncated:
        result["note"] = (
            f"only the first {MAX_FETCH_BYTES} bytes were read; the rest of the page was not seen"
        )
    return result


# --- Local command tool -------------------------------------------------------


def _bash_environment():
    # Only what local commands need; API keys and tokens are never inherited.
    env = {key: os.environ[key] for key in BASH_ENV_KEYS if key in os.environ}
    env.setdefault("PATH", "/usr/bin:/bin")
    env.update({"TERM": "dumb", "PYTHONDONTWRITEBYTECODE": "1"})
    return env


def _stop_group(process):
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def bash(runtime, command):
    """Run an already-approved command; stop its process group at any limit."""
    process = subprocess.Popen(
        ["/bin/bash", "--noprofile", "--norc", "-c", command],
        cwd=runtime.root,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=_bash_environment(),
        start_new_session=True,
    )
    output = bytearray()
    stopped = None
    deadline = time.monotonic() + BASH_TIMEOUT
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    stopped = f"timed out after {BASH_TIMEOUT} seconds"
                    break
                if not selector.select(remaining):
                    continue
                chunk = os.read(process.stdout.fileno(), 4096)
                if not chunk:
                    break
                output += chunk
                if len(output) > MAX_BASH_OUTPUT:
                    stopped = f"output exceeded {MAX_BASH_OUTPUT} bytes"
                    break
        if stopped is None:
            try:
                process.wait(timeout=max(0.0, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                stopped = f"timed out after {BASH_TIMEOUT} seconds"
    finally:
        # Also runs on Ctrl+C, and removes any background children left behind.
        _stop_group(process)
        process.wait()
        process.stdout.close()

    text = output[:MAX_BASH_OUTPUT].decode("utf-8", "replace")
    if stopped:
        raise ToolError(f"command stopped: {stopped}. Partial output:\n{text}")
    return {"exit_code": process.returncode, "output": text}


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
        fixtures_dir=DEFAULT_FIXTURES_DIR,
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
        self.fixtures_dir = Path(fixtures_dir)
        self.fetch_opener = urllib.request.build_opener(_RejectRedirects)

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
