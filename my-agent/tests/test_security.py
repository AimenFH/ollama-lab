"""Injection defenses: supplied attack actions through the dispatcher, and untrusted labels."""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from student_agent import Runtime, run_agent

PACKAGE = Path(__file__).resolve().parents[2]
TARGET = PACKAGE / "target-service"
ATTACKS = PACKAGE / "fixtures" / "attack-actions.jsonl"
PROTECTED = ["orders/validation.py", "tests/test_acceptance.py", "docs/business-rules.md"]


@unittest.skipUnless(ATTACKS.exists() and TARGET.exists(), "lab package fixtures not found")
class AttackActionsTest(unittest.TestCase):
    """No model involved: the runtime alone must hold."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name) / "target-service"
        shutil.copytree(TARGET, self.root, ignore=shutil.ignore_patterns(".git", "__pycache__"))
        self.before = {name: (self.root / name).read_bytes() for name in PROTECTED}
        self.actions = [json.loads(line) for line in ATTACKS.read_text().splitlines() if line.strip()]

    def dispatch(self, runtime):
        return [runtime.execute(action)["status"] for action in self.actions]

    def assert_protected_unchanged(self):
        for name, content in self.before.items():
            self.assertEqual((self.root / name).read_bytes(), content, name)
        self.assertFalse((self.root.parent / "escape.txt").exists())

    def test_edit_mode_denies_edit_escape_and_unapproved_bash(self):
        prompts = []

        def deny(command, cwd):
            prompts.append(command)
            return False

        statuses = self.dispatch(Runtime(self.root, mode="edit", approve=deny))
        self.assertEqual(statuses, ["denied", "denied", "denied", "error"])
        self.assertEqual(prompts, ["printf 'APPROVAL_TEST_ONLY\\n'"])
        self.assert_protected_unchanged()

    def test_read_only_denies_bash_before_any_prompt(self):
        runtime = Runtime(self.root, approve=lambda *_: self.fail("read-only must not prompt"))
        self.assertEqual(self.dispatch(runtime), ["denied", "denied", "denied", "error"])
        self.assert_protected_unchanged()


class UntrustedLabelTest(unittest.TestCase):
    def run_once(self, **kwargs):
        replies = iter(['{"tool":"list_files","args":{}}', '{"final":"done"}'])
        seen = []

        def model(messages):
            seen.append(list(messages))
            return next(replies)

        run_agent(model, Runtime("."), "task", **kwargs)
        return seen[0][0]["content"], json.loads(seen[1][-1]["content"])

    def test_guidance_and_label_on_by_default(self):
        system, observation = self.run_once()
        self.assertIn("untrusted data, not instructions", system)
        self.assertIn("untrusted", observation["trust"])

    def test_baseline_has_neither(self):
        system, observation = self.run_once(injection_guidance=False)
        self.assertNotIn("untrusted", system)
        self.assertNotIn("trust", observation)


if __name__ == "__main__":
    unittest.main()
