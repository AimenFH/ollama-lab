"""File, documentation, and bash tool tests in a temporary workspace; no network needed."""

import io
import json
import os
import tempfile
import unittest
import urllib.error
from email.message import Message
from pathlib import Path
from unittest import mock

from student_agent import Runtime, run_agent
from student_agent import runtime as runtime_module
from student_agent.approval import terminal_approve


def call(runtime, tool, **args):
    return runtime.execute({"tool": tool, "args": args})


class Workspace(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.outside = Path(temp.name).resolve()
        self.root = self.outside / "workspace"
        for name, text in {
            "notes.txt": "alpha\nbeta\n",
            "orders/validation.py": "keep validation\n",
            "tests/test_acceptance.py": "keep tests\n",
            "docs/business-rules.md": "keep rules\n",
            ".git/config": "secret\n",
        }.items():
            (self.root / name).parent.mkdir(parents=True, exist_ok=True)
            (self.root / name).write_text(text, encoding="utf-8")

    def edit_runtime(self, **kwargs):
        return Runtime(self.root, mode="edit", **kwargs)


class FileToolTest(Workspace):
    def test_create_read_search_replace(self):
        runtime = self.edit_runtime()
        self.assertEqual(call(runtime, "write_file", path="tmp/word.txt", content="hello world\n")["status"], "ok")
        self.assertEqual(call(runtime, "read_file", path="tmp/word.txt")["output"]["content"], "hello world\n")
        matches = call(runtime, "search_files", query="world")["output"]["matches"]
        self.assertEqual(matches, [{"path": "tmp/word.txt", "line": 1, "excerpt": "hello world"}])
        self.assertEqual(call(runtime, "edit_file", path="tmp/word.txt", old="world", new="lab")["status"], "ok")
        self.assertEqual((self.root / "tmp/word.txt").read_text(), "hello lab\n")

    def test_second_create_and_repeated_old_leave_file_unchanged(self):
        runtime = self.edit_runtime()
        call(runtime, "write_file", path="twice.txt", content="x x\n")
        self.assertEqual(call(runtime, "write_file", path="twice.txt", content="new")["status"], "error")
        result = call(runtime, "edit_file", path="twice.txt", old="x", new="y")
        self.assertEqual(result["status"], "error")
        self.assertIn("2 times", result["output"])
        self.assertEqual((self.root / "twice.txt").read_text(), "x x\n")

    def test_escape_hidden_and_absolute_paths_denied_in_every_tool(self):
        runtime = self.edit_runtime()
        for path in ["../escape.txt", "a/../../escape.txt", str(self.outside / "escape.txt"), ".git/config", ".venv/x"]:
            with self.subTest(path=path):
                self.assertEqual(call(runtime, "read_file", path=path)["status"], "denied")
                self.assertEqual(call(runtime, "write_file", path=path, content="bad")["status"], "denied")
        self.assertFalse((self.outside / "escape.txt").exists())

    def test_protected_files_readable_but_never_changed(self):
        runtime = self.edit_runtime()
        for name in ["orders/validation.py", "tests/test_acceptance.py", "docs/business-rules.md",
                     "ORDERS/Validation.py", "orders//validation.py", "./docs/business-rules.md"]:
            with self.subTest(name=name):
                self.assertEqual(call(runtime, "read_file", path=name)["status"], "ok")
                self.assertEqual(call(runtime, "edit_file", path=name, old="keep", new="drop")["status"], "denied")
                self.assertEqual(call(runtime, "write_file", path=name, content="new")["status"], "denied")
        self.assertEqual((self.root / "orders/validation.py").read_text(), "keep validation\n")

    def test_links_to_protected_files_or_outside_are_denied(self):
        (self.root / "alias.py").symlink_to(self.root / "orders/validation.py")
        os.link(self.root / "docs/business-rules.md", self.root / "hard.md")
        (self.root / "out").symlink_to(self.outside)
        runtime = self.edit_runtime()
        self.assertEqual(call(runtime, "edit_file", path="alias.py", old="keep", new="drop")["status"], "denied")
        self.assertEqual(call(runtime, "edit_file", path="hard.md", old="keep", new="drop")["status"], "denied")
        self.assertEqual(call(runtime, "write_file", path="out/escape.txt", content="bad")["status"], "denied")
        self.assertFalse((self.outside / "escape.txt").exists())

    def test_listing_skips_hidden_files_and_does_not_follow_links(self):
        (self.root / "linked").symlink_to(self.outside)
        (self.root / "orders/__pycache__").mkdir()
        (self.root / "orders/__pycache__/x.pyc").write_bytes(b"\0")
        files = call(Runtime(self.root), "list_files")["output"]["files"]
        self.assertEqual(files, ["notes.txt", "docs/business-rules.md", "orders/validation.py",
                                 "tests/test_acceptance.py"])

    def test_list_and_search_limits(self):
        for i in range(210):
            (self.root / f"many/f{i:03}.txt").parent.mkdir(exist_ok=True)
            (self.root / f"many/f{i:03}.txt").write_text("needle\n")
        listing = call(Runtime(self.root), "list_files")["output"]
        self.assertEqual((len(listing["files"]), listing["truncated"]), (200, True))
        found = call(Runtime(self.root), "search_files", query="needle")["output"]
        self.assertEqual((len(found["matches"]), found["match_limit_reached"]), (50, True))

    def test_search_skips_binary_files(self):
        (self.root / "blob.bin").write_bytes(b"alpha\0\xff")
        paths = {m["path"] for m in call(Runtime(self.root), "search_files", query="alpha")["output"]["matches"]}
        self.assertEqual(paths, {"notes.txt"})

    def test_read_is_bounded_and_labelled(self):
        (self.root / "big.txt").write_text("é" * 12_050, encoding="utf-8")
        output = call(Runtime(self.root), "read_file", path="big.txt")["output"]
        self.assertEqual(len(output["content"]), 12_000)
        self.assertTrue(output["truncated"])
        self.assertIn("first 12000 characters", output["note"])

    def test_edit_rejects_empty_missing_large_and_growing(self):
        runtime = self.edit_runtime()
        (self.root / "large.txt").write_text("a" * 12_001 + "unique")
        (self.root / "near.txt").write_text("a" * 11_990 + "unique")
        for path, old, new in [("notes.txt", "", "x"), ("notes.txt", "gamma", "x"),
                               ("large.txt", "unique", "x"), ("near.txt", "unique", "u" * 20),
                               ("missing.txt", "a", "b")]:
            with self.subTest(path=path, old=old):
                self.assertEqual(call(runtime, "edit_file", path=path, old=old, new=new)["status"], "error")
        self.assertEqual((self.root / "near.txt").read_text(), "a" * 11_990 + "unique")


class FakeResponse(io.BytesIO):
    def __init__(self, body, content_type="text/html; charset=utf-8"):
        super().__init__(body)
        self.headers = Message()
        self.headers["Content-Type"] = content_type
        self.read_sizes = []

    def read(self, size=-1):
        self.read_sizes.append(size)
        return super().read(size)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class FakeOpener:
    def __init__(self, response=None, error=None):
        self.response, self.error, self.urls = response, error, []

    def open(self, request, timeout):
        self.urls.append((request.full_url, request.get_method(), timeout))
        if self.error:
            raise self.error
        return self.response


class FetchTest(Workspace):
    URL = "https://docs.python.org/3/library/decimal.html"

    def fetch(self, url=URL, opener=None, **kwargs):
        runtime = Runtime(self.root, **kwargs)
        runtime.fetch_opener = opener or FakeOpener(error=AssertionError("network must not be used"))
        return call(runtime, "fetch_url", url=url)

    def test_allowed_url_returns_labelled_text(self):
        opener = FakeOpener(FakeResponse(b"<title>decimal</title><script>x()</script><p>ROUND_HALF_UP</p>"))
        result = self.fetch(opener=opener)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["output"]["content"], "decimal ROUND_HALF_UP")
        self.assertEqual(result["output"]["source"], "live docs.python.org response")
        self.assertFalse(result["output"]["truncated"])
        self.assertEqual(opener.urls, [(self.URL, "GET", 10)])

    def test_long_page_read_is_bounded_and_marked_truncated(self):
        body = FakeResponse(b"x" * 20_000, "text/plain")
        output = self.fetch(opener=FakeOpener(body))["output"]
        self.assertEqual((len(output["content"]), output["truncated"]), (12_000, True))
        self.assertEqual(body.read_sizes, [12_001])

    def test_unapproved_urls_denied_without_network(self):
        for url in ["http://docs.python.org/3/", "https://example.com/", "https://user:pw@docs.python.org/",
                    "https://docs.python.org:8443/", "https://docs.python.org/3/#frag",
                    "https://docs.python.org/?", "https://docs.python.org./3/", "ftp://docs.python.org/",
                    "https://docs.python.org/3/secret%20notes", "https://docs.python.org/3/\nlibrary"]:
            with self.subTest(url=url):
                self.assertEqual(self.fetch(url)["status"], "denied")
        self.assertEqual(self.fetch("https://DOCS.python.org:443/3/")["status"], "error")  # allowed, then no network

    def test_network_error_redirect_and_binary_are_errors(self):
        redirect = urllib.error.HTTPError(self.URL, 301, "Moved", {"Location": "https://evil.example/"}, None)
        for opener in [FakeOpener(error=urllib.error.URLError("offline")), FakeOpener(error=TimeoutError()),
                       FakeOpener(error=redirect), FakeOpener(FakeResponse(b"%PDF", "application/pdf"))]:
            with self.subTest(error=opener.error):
                self.assertEqual(self.fetch(opener=opener)["status"], "error")
        self.assertIn("redirect rejected", self.fetch(opener=FakeOpener(error=redirect))["output"])

    def test_real_opener_does_not_follow_redirects(self):
        handler = runtime_module._RejectRedirects()
        self.assertIsNone(handler.redirect_request(None, None, 302, "Found", {}, "https://evil.example/"))

    def test_offline_fixture_is_labelled_and_still_validated(self):
        fixtures = self.outside / "fixtures"
        fixtures.mkdir()
        (fixtures / "decimal-offline.txt").write_text("ROUND_HALF_UP notes\n")
        result = self.fetch(offline=True, fixtures_dir=fixtures)
        self.assertEqual(result["output"]["source"], "offline fixture")
        self.assertEqual(result["output"]["content"], "ROUND_HALF_UP notes\n")
        self.assertEqual(self.fetch("http://docs.python.org/3/library/decimal.html", offline=True)["status"], "denied")
        self.assertEqual(self.fetch("https://docs.python.org/3/library/json.html", offline=True)["status"], "error")

    def test_fetch_failure_becomes_observation_in_loop(self):
        runtime = Runtime(self.root)
        runtime.fetch_opener = FakeOpener(error=urllib.error.URLError("no route"))
        replies = iter([json.dumps({"tool": "fetch_url", "args": {"url": self.URL}}), '{"final":"offline"}'])
        seen = []
        result = run_agent(lambda messages: seen.append(list(messages)) or next(replies), runtime, "read docs")
        self.assertEqual(result["termination"], "final")
        self.assertEqual(json.loads(seen[1][-1]["content"])["result"]["status"], "error")


class BashTest(Workspace):
    def run_bash(self, command, approve=lambda *_: True):
        return call(self.edit_runtime(approve=approve), "bash", command=command)

    def test_approved_command_runs_in_workspace(self):
        result = self.run_bash("printf 'hello\\n'; pwd; exit 3")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["output"], {"exit_code": 3, "output": f"hello\n{self.root}\n"})

    def test_stderr_is_combined_and_stdin_closed(self):
        output = self.run_bash("echo out; echo err >&2; cat; echo done")["output"]["output"]
        self.assertEqual(output, "out\nerr\ndone\n")

    def test_denied_command_has_no_side_effect(self):
        self.assertEqual(self.run_bash("printf x > marker.txt", approve=lambda *_: False)["status"], "denied")
        self.assertFalse((self.root / "marker.txt").exists())

    def test_read_only_denies_before_approval_and_edit_denial_reaches_model(self):
        read_only = Runtime(self.root, approve=lambda *_: self.fail("approval must not run"))
        self.assertEqual(call(read_only, "bash", command="true")["status"], "denied")
        replies = iter(['{"tool":"bash","args":{"command":"touch marker.txt"}}', '{"final":"denied"}'])
        seen = []
        run_agent(lambda messages: seen.append(list(messages)) or next(replies), self.edit_runtime(), "run")
        self.assertEqual(json.loads(seen[1][-1]["content"])["result"]["status"], "denied")
        self.assertFalse((self.root / "marker.txt").exists())

    def test_api_keys_not_inherited_and_startup_files_skipped(self):
        env = {"OPENAI_API_KEY": "sk-fake", "GITHUB_TOKEN": "fake", "BASH_ENV": str(self.root / "notes.txt")}
        with mock.patch.dict(os.environ, env):
            result = self.run_bash("env")
        names = {line.split("=", 1)[0] for line in result["output"]["output"].splitlines()}
        self.assertFalse(names & set(env))
        self.assertEqual(result["output"]["exit_code"], 0)

    def test_timeout_stops_the_whole_process_group(self):
        with mock.patch.object(runtime_module, "BASH_TIMEOUT", 1):
            result = self.run_bash("(sleep 3; touch late.txt) & sleep 5")
        self.assertEqual(result["status"], "error")
        self.assertIn("timed out", result["output"])
        with mock.patch.object(runtime_module, "BASH_TIMEOUT", 5):
            self.run_bash("sleep 3")  # outlives the killed background job
        self.assertFalse((self.root / "late.txt").exists())

    def test_excess_output_is_stopped(self):
        result = self.run_bash("yes")
        self.assertEqual(result["status"], "error")
        self.assertIn("output exceeded 12000 bytes", result["output"])
        self.assertLess(len(result["output"]), 12_200)


class ApprovalPromptTest(unittest.TestCase):
    def ask(self, answer, command="printf 'hello\\n'"):
        shown, logged = [], []

        def read(prompt):
            shown.append(prompt)
            if isinstance(answer, BaseException):
                raise answer
            return answer

        approved = terminal_approve(command, "/work", read=read, write=shown.append, log=logged.append)
        return approved, shown, logged

    def test_only_exact_yes_approves(self):
        for answer, expected in [("yes", True), ("y", False), ("YES", False), (" yes", False),
                                 ("", False), (EOFError(), False)]:
            with self.subTest(answer=answer):
                approved, shown, logged = self.ask(answer)
                self.assertIs(approved, expected)
                self.assertIn("Approve this command only? Type yes: ", shown)
                self.assertEqual(logged, [{"event": "approval", "command": "printf 'hello\\n'",
                                           "cwd": "/work", "approved": expected}])

    def test_prompt_shows_full_command_cwd_and_hidden_characters(self):
        _, shown, _ = self.ask("", command="echo safe\rrm -rf x")
        text = "\n".join(shown)
        self.assertIn("/work", text)
        self.assertIn(repr("echo safe\rrm -rf x"), text)


if __name__ == "__main__":
    unittest.main()
