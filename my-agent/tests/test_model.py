"""Ollama adapter tests with a fake HTTP opener; no Ollama needed."""

import io
import json
import unittest
import urllib.error

from student_agent.model import ModelError, OllamaModel


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class FakeOpener:
    def __init__(self, body=None, error=None):
        self.body = body
        self.error = error
        self.requests = []

    def open(self, request, timeout):
        self.requests.append((request, timeout))
        if self.error:
            raise self.error
        return FakeResponse(self.body)


def model_with(opener, **kwargs):
    model = OllamaModel("qwen2.5-coder:7b", **kwargs)
    model._opener = opener
    return model


class OllamaModelTest(unittest.TestCase):
    def test_request_is_bounded_json_chat(self):
        opener = FakeOpener(json.dumps({"message": {"content": '{"final":"ok"}'}}).encode())
        messages = [{"role": "user", "content": "hi"}]

        self.assertEqual(model_with(opener)(messages), '{"final":"ok"}')

        request, timeout = opener.requests[0]
        body = json.loads(request.data)
        self.assertEqual(request.full_url, "http://127.0.0.1:11434/api/chat")
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(timeout, 90)
        self.assertEqual(body["model"], "qwen2.5-coder:7b")
        self.assertEqual(body["messages"], messages)
        self.assertIs(body["stream"], False)
        self.assertEqual(body["format"], "json")
        self.assertEqual(body["options"]["temperature"], 0)
        self.assertEqual(body["options"]["num_predict"], 2048)

    def test_oversized_response_is_rejected(self):
        opener = FakeOpener(b"x" * 101)
        with self.assertRaises(ModelError):
            model_with(opener, max_response_bytes=100)([])

    def test_unexpected_shape_is_rejected(self):
        for body in [b"not json", b"{}", b'{"message": {"content": 5}}']:
            with self.subTest(body=body), self.assertRaises(ModelError):
                model_with(FakeOpener(body))([])

    def test_connection_failures_become_model_errors(self):
        http_error = urllib.error.HTTPError(
            "http://127.0.0.1:11434/api/chat", 404, "Not Found", {},
            io.BytesIO(b'{"error":"model not found"}'),
        )
        for error in [urllib.error.URLError("refused"), TimeoutError("slow"), http_error]:
            with self.subTest(error=error), self.assertRaises(ModelError) as caught:
                model_with(FakeOpener(error=error))([])
        self.assertIn("model not found", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
