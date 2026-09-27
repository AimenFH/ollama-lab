"""First tests for the action-observation loop."""

import json
import unittest

from student_agent import run_agent


class RecordingRuntime:
    def __init__(self):
        self.actions = []

    def execute(self, action):
        self.actions.append(action)
        return {"status": "ok", "output": "example file content"}


class LoopTest(unittest.TestCase):
    def test_tool_observation_then_final(self):
        responses = iter(
            [
                '{"tool":"read_file","args":{"path":"orders/pricing.py"}}',
                '{"final":"Inspected pricing."}',
            ]
        )
        messages_seen = []

        def fake_model(messages):
            messages_seen.append(list(messages))
            return next(responses)

        runtime = RecordingRuntime()
        result = run_agent(fake_model, runtime, "Inspect pricing", max_turns=2)

        self.assertEqual(result["termination"], "final")
        self.assertEqual(runtime.actions[0]["tool"], "read_file")
        observation = json.loads(messages_seen[1][-1]["content"])
        self.assertEqual(observation["result"]["status"], "ok")

    def test_invalid_json_consumes_a_turn(self):
        responses = iter(["not JSON", '{"final":"Recovered."}'])
        messages_seen = []

        def fake_model(messages):
            messages_seen.append(list(messages))
            return next(responses)

        result = run_agent(
            fake_model,
            RecordingRuntime(),
            "Inspect pricing",
            max_turns=2,
        )

        self.assertEqual(result["termination"], "final")
        self.assertIn("error", messages_seen[1][-1]["content"])


if __name__ == "__main__":
    unittest.main()
