"""Action-observation loop tests with fake models; no Ollama needed."""

import json
import unittest

from student_agent import Runtime, run_agent


class RecordingRuntime:
    def __init__(self, result=None):
        self.actions = []
        self.result = result or {"status": "ok", "output": "example file content"}

    def execute(self, action):
        self.actions.append(action)
        return self.result


def scripted(*responses):
    replies = iter(responses)
    seen = []

    def model(messages):
        seen.append(list(messages))
        return next(replies)

    return model, seen


class LoopTest(unittest.TestCase):
    def test_tool_observation_then_final(self):
        model, seen = scripted(
            '{"tool":"read_file","args":{"path":"orders/pricing.py"}}',
            '{"final":"Inspected pricing."}',
        )
        runtime = RecordingRuntime()
        result = run_agent(model, runtime, "Inspect pricing", max_turns=2)

        self.assertEqual(result["termination"], "final")
        self.assertEqual(result["final"], "Inspected pricing.")
        self.assertEqual(runtime.actions[0]["tool"], "read_file")
        observation = json.loads(seen[1][-1]["content"])
        self.assertEqual(observation["result"]["status"], "ok")
        self.assertEqual(seen[1][-1]["role"], "user")

    def test_invalid_json_consumes_a_turn(self):
        model, seen = scripted("not JSON", '{"final":"Recovered."}')
        runtime = RecordingRuntime()
        result = run_agent(model, runtime, "Inspect pricing", max_turns=2)

        self.assertEqual(result["termination"], "final")
        self.assertEqual(result["turns"], 2)
        self.assertIn("error", seen[1][-1]["content"])
        self.assertEqual(runtime.actions, [])

    def test_wrong_shapes_are_protocol_errors(self):
        for bad in ['[1, 2]', '{"tool":"read_file"}', '{"final":""}',
                    '{"final":"x","tool":"read_file","args":{}}', '{"tool":"read_file","args":"x"}']:
            with self.subTest(bad=bad):
                model, seen = scripted(bad, '{"final":"done"}')
                runtime = RecordingRuntime()
                run_agent(model, runtime, "task", max_turns=2)
                self.assertEqual(runtime.actions, [])
                self.assertEqual(json.loads(seen[1][-1]["content"])["result"]["status"], "error")

    def test_turn_limit(self):
        calls = []

        def model(messages):
            calls.append(1)
            return '{"tool":"list_files","args":{}}'

        result = run_agent(model, RecordingRuntime(), "task", max_turns=3)
        self.assertEqual(result["termination"], "turn_limit")
        self.assertEqual(len(calls), 3)

    def test_model_failure_stops_with_reason(self):
        def model(messages):
            raise TimeoutError("no reply in 90 s")

        result = run_agent(model, RecordingRuntime(), "task")
        self.assertEqual(result["termination"], "model_error")
        self.assertIn("no reply in 90 s", result["reason"])

    def test_ctrl_c_during_model_or_tool_cancels(self):
        def model(messages):
            raise KeyboardInterrupt

        self.assertEqual(run_agent(model, RecordingRuntime(), "task")["termination"], "cancelled")

        class InterruptedRuntime:
            def execute(self, action):
                raise KeyboardInterrupt

        model, _ = scripted('{"tool":"list_files","args":{}}')
        self.assertEqual(run_agent(model, InterruptedRuntime(), "task")["termination"], "cancelled")

    def test_crashing_tool_becomes_observation(self):
        class CrashingRuntime:
            def execute(self, action):
                raise OSError("disk unplugged")

        model, seen = scripted('{"tool":"list_files","args":{}}', '{"final":"done"}')
        result = run_agent(model, CrashingRuntime(), "task")
        self.assertEqual(result["termination"], "final")
        self.assertIn("disk unplugged", seen[1][-1]["content"])

    def test_events_record_requests_results_and_termination(self):
        model, _ = scripted('{"tool":"read_file","args":{"path":"a.txt"}}', '{"final":"done"}')
        events = []
        run_agent(model, RecordingRuntime(), "task", emit=events.append)
        self.assertEqual([e["event"] for e in events], ["request", "result", "final", "termination"])
        self.assertEqual(events[1]["result"]["status"], "ok")
        for event in events:
            json.dumps(event)

    def test_denial_reaches_model_as_data(self):
        model, seen = scripted(
            '{"tool":"bash","args":{"command":"printf hi"}}',
            '{"final":"bash was denied"}',
        )
        runtime = Runtime(".", mode="read-only", approve=lambda *_: self.fail("must not ask"))
        result = run_agent(model, runtime, "task")
        self.assertEqual(result["termination"], "final")
        observation = seen[1][-1]
        self.assertEqual(observation["role"], "user")
        self.assertEqual(json.loads(observation["content"])["result"]["status"], "denied")
        self.assertEqual(sum(m["role"] == "system" for m in seen[1]), 1)

    def test_repeated_failed_request_gets_controller_note(self):
        request = '{"tool":"bash","args":{"command":"printf hi"}}'
        model, seen = scripted(request, request, '{"tool":"list_files","args":{}}', request, '{"final":"x"}')
        run_agent(model, RecordingRuntime({"status": "denied", "output": "no"}), "task")
        notes = [("controller_note" in json.loads(s[-1]["content"])) for s in seen[1:]]
        self.assertEqual(notes, [False, True, False, False])

    def test_system_prompt_lists_only_advertised_tools(self):
        model, seen = scripted('{"final":"done"}')
        run_agent(model, Runtime(".", mode="read-only", enabled={"read_file", "bash"}), "task")
        system = seen[0][0]["content"]
        self.assertIn("read_file(path)", system)
        self.assertNotIn("bash(command)", system)
        self.assertNotIn("list_files(", system)
        self.assertEqual(seen[0][1], {"role": "user", "content": "task"})


if __name__ == "__main__":
    unittest.main()
