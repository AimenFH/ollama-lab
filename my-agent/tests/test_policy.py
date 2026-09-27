"""Registry and permission-policy tests."""

import unittest

from student_agent import Runtime


def call(runtime, tool, **args):
    return runtime.execute({"tool": tool, "args": args})


class PolicyTest(unittest.TestCase):
    def test_read_only_denies_mutation_before_approval(self):
        runtime = Runtime(".", approve=lambda *_: self.fail("approval must not be reached"))
        for tool, args in [("write_file", {"path": "x", "content": "y"}),
                           ("edit_file", {"path": "x", "old": "a", "new": "b"}),
                           ("bash", {"command": "printf blocked"})]:
            self.assertEqual(call(runtime, tool, **args)["status"], "denied")

    def test_disabled_tool_denied_even_if_model_asks(self):
        runtime = Runtime(".", enabled={"list_files"})
        self.assertEqual(call(runtime, "read_file", path="a.txt")["status"], "denied")
        self.assertEqual([t["name"] for t in runtime.describe_tools()], ["list_files"])

    def test_advertised_tools_respect_mode_and_enabled(self):
        read_only = {t["name"] for t in Runtime(".").describe_tools()}
        edit = {t["name"] for t in Runtime(".", mode="edit").describe_tools()}
        self.assertEqual(read_only, {"list_files", "read_file", "search_files", "fetch_url"})
        self.assertEqual(edit, read_only | {"write_file", "edit_file", "bash"})

    def test_malformed_actions_are_errors(self):
        runtime = Runtime(".")
        for action in [None, [], {}, {"tool": "missing", "args": {}},
                       {"tool": "read_file"}, {"tool": "read_file", "args": []},
                       {"tool": "read_file", "args": {"path": 12}},
                       {"tool": "read_file", "args": {}},
                       {"tool": "read_file", "args": {"path": "a", "extra": "b"}},
                       {"tool": "read_file", "args": {"path": "a" * 12_001}}]:
            with self.subTest(action=action):
                self.assertEqual(runtime.execute(action)["status"], "error")

    def test_bash_asks_once_and_needs_exact_true(self):
        asked = []

        def approve(command, cwd):
            asked.append((command, cwd))
            return "yes"

        runtime = Runtime(".", mode="edit", approve=approve)
        self.assertEqual(call(runtime, "bash", command="printf hi")["status"], "denied")
        self.assertEqual(asked, [("printf hi", str(runtime.root))])

    def test_default_approval_denies(self):
        self.assertEqual(call(Runtime(".", mode="edit"), "bash", command="printf hi")["status"], "denied")

    def test_crashing_approval_callback_denies(self):
        def approve(command, cwd):
            raise EOFError

        self.assertEqual(call(Runtime(".", mode="edit", approve=approve), "bash", command="true")["status"], "denied")

    def test_bad_configuration_fails_fast(self):
        with self.assertRaises(ValueError):
            Runtime(".", mode="admin")
        with self.assertRaises(ValueError):
            Runtime(".", enabled={"read_file", "rm_rf"})


if __name__ == "__main__":
    unittest.main()
