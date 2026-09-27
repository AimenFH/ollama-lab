"""Public behavior checks. Run against YOUR module; no student agent is supplied.
python checks/check_agent.py --implementation ../my-agent --module student_agent
"""
import argparse
import importlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

IMPLEMENTATION = None


class AgentContract(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "workspace"
        self.root.mkdir()
        (self.root / "notes.txt").write_text("alpha\nbeta\n", encoding="utf-8")
        (self.root / "orders").mkdir()
        (self.root / "orders/validation.py").write_text("keep validation\n", encoding="utf-8")

    def runtime(self, **kwargs):
        return IMPLEMENTATION.Runtime(self.root, **kwargs)

    def call(self, runtime, tool, **args):
        return runtime.execute({"tool": tool, "args": args})

    def test_read_and_search(self):
        runtime = self.runtime()
        self.assertEqual(self.call(runtime, "read_file", path="notes.txt")["status"], "ok")
        self.assertIn("notes.txt", str(self.call(runtime, "search_files", query="alpha")))

    def test_read_only_rejects_all_mutation_tools(self):
        runtime = self.runtime(approve=lambda *_: self.fail("approval should not be reached"))
        for name, args in [("write_file", {"path": "new.txt", "content": "bad"}),
                           ("edit_file", {"path": "notes.txt", "old": "alpha", "new": "bad"}),
                           ("bash", {"command": "printf blocked"})]:
            self.assertEqual(self.call(runtime, name, **args)["status"], "denied")
        self.assertFalse((self.root / "new.txt").exists())
        self.assertEqual((self.root / "notes.txt").read_text(), "alpha\nbeta\n")

    def test_disabled_tool_cannot_be_called_directly(self):
        self.assertEqual(self.call(self.runtime(enabled={"list_files"}), "read_file", path="notes.txt")["status"], "denied")

    def test_protected_file_cannot_be_edited(self):
        runtime = self.runtime(mode="edit")
        self.assertEqual(self.call(runtime, "edit_file", path="orders/validation.py", old="keep", new="remove")["status"], "denied")
        self.assertEqual((self.root / "orders/validation.py").read_text(), "keep validation\n")

    def test_path_escape_and_absolute_path(self):
        runtime = self.runtime(mode="edit")
        for path in ["../escape.txt", str(self.root.parent / "escape.txt"), ".git/config"]:
            self.assertEqual(self.call(runtime, "write_file", path=path, content="bad")["status"], "denied")
        self.assertFalse((self.root.parent / "escape.txt").exists())

    def test_symlink_escape(self):
        outside = self.root.parent / "outside.txt"
        outside.write_text("outside")
        (self.root / "link.txt").symlink_to(outside)
        self.assertEqual(self.call(self.runtime(), "read_file", path="link.txt")["status"], "denied")

    def test_create_does_not_overwrite(self):
        runtime = self.runtime(mode="edit")
        self.assertEqual(self.call(runtime, "write_file", path="new.txt", content="first")["status"], "ok")
        self.assertEqual(self.call(runtime, "write_file", path="new.txt", content="second")["status"], "error")
        self.assertEqual((self.root / "new.txt").read_text(), "first")

    def test_exact_edit_and_ambiguous_edit(self):
        runtime = self.runtime(mode="edit")
        self.assertEqual(self.call(runtime, "edit_file", path="notes.txt", old="alpha", new="beta")["status"], "ok")
        for old in ["missing", "beta", ""]:
            self.assertEqual(self.call(runtime, "edit_file", path="notes.txt", old=old, new="bad")["status"], "error")
        self.assertEqual((self.root / "notes.txt").read_text(), "beta\nbeta\n")

    def test_bash_denial_has_no_side_effect(self):
        approvals = []
        def deny(command, cwd):
            approvals.append((command, cwd))
            return False
        result = self.call(self.runtime(mode="edit", approve=deny), "bash", command="printf harmless > marker.txt")
        self.assertEqual(result["status"], "denied")
        self.assertEqual(len(approvals), 1)
        self.assertFalse((self.root / "marker.txt").exists())

    def test_malformed_requests_return_errors(self):
        runtime = self.runtime()
        for action in [None, [], {}, {"tool": "missing", "args": {}},
                       {"tool": "read_file", "args": {"path": 12}},
                       {"tool": "read_file", "args": {"path": "notes.txt", "extra": True}}]:
            self.assertEqual(runtime.execute(action)["status"], "error")

    def test_fetch_rejects_unapproved_urls_without_network(self):
        for url in ["http://docs.python.org", "https://example.com", "https://docs.python.org.evil.invalid", "https://docs.python.org/?secret=fake"]:
            self.assertEqual(self.call(self.runtime(), "fetch_url", url=url)["status"], "denied")

    def test_invalid_json_consumes_turn_and_recovers(self):
        responses = iter(["not JSON", '{"final":"cannot complete yet"}'])
        messages_seen = []
        def model(messages):
            messages_seen.append(list(messages))
            return next(responses)
        result = IMPLEMENTATION.run_agent(model, self.runtime(), "inspect", max_turns=2)
        self.assertEqual(result["termination"], "final")
        self.assertIn("error", messages_seen[1][-1]["content"])

    def test_turn_limit(self):
        calls = []
        def model(messages):
            calls.append(1)
            return '{"tool":"list_files","args":{}}'
        result = IMPLEMENTATION.run_agent(model, self.runtime(), "inspect", max_turns=3)
        self.assertEqual(result["termination"], "turn_limit")
        self.assertEqual(len(calls), 3)

    def test_model_failure_and_cancellation(self):
        for error, expected in [(TimeoutError(), "model_error"), (KeyboardInterrupt(), "cancelled")]:
            def model(messages):
                raise error
            self.assertEqual(IMPLEMENTATION.run_agent(model, self.runtime(), "inspect")["termination"], expected)

    def test_scripted_injection_cannot_change_protected_file(self):
        responses = iter([
            json.dumps({"tool": "edit_file", "args": {"path": "orders/validation.py", "old": "keep", "new": "remove"}}),
            '{"final":"stopped"}',
        ])
        events = []
        IMPLEMENTATION.run_agent(lambda _: next(responses), self.runtime(mode="edit"), "repair pricing", emit=events.append)
        self.assertTrue(any(e.get("result", {}).get("status") == "denied" for e in events))
        self.assertEqual((self.root / "orders/validation.py").read_text(), "keep validation\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--implementation", required=True, help="directory containing your module")
    parser.add_argument("--module", default="student_agent")
    args = parser.parse_args()
    sys.path.insert(0, str(Path(args.implementation).resolve()))
    IMPLEMENTATION = importlib.import_module(args.module)
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(AgentContract)
    raise SystemExit(not unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful())
