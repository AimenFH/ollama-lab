"""Local Ollama chat adapter."""

import json
import urllib.error
import urllib.request

DEFAULT_ENDPOINT = "http://127.0.0.1:11434/api/chat"


class ModelError(RuntimeError):
    """Ollama could not produce a usable reply."""


class OllamaModel:
    """Callable adapter for Ollama's local chat endpoint."""

    def __init__(
        self,
        model_name,
        endpoint=DEFAULT_ENDPOINT,
        timeout=90,
        max_output_tokens=2048,
        context_tokens=16384,
        max_response_bytes=1_000_000,
    ):
        self.model_name = model_name
        self.endpoint = endpoint
        self.timeout = timeout
        self.max_output_tokens = max_output_tokens
        # Ollama's default context is small and silently drops the oldest messages,
        # including the system prompt, once the history grows past it.
        self.context_tokens = context_tokens
        self.max_response_bytes = max_response_bytes
        # No proxy: conversation content must stay on this machine.
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def request_body(self, messages):
        return {
            "model": self.model_name,
            "messages": messages,
            "stream": False,
            "format": "json",
            "options": {
                "temperature": 0,
                "num_predict": self.max_output_tokens,
                "num_ctx": self.context_tokens,
            },
        }

    def __call__(self, messages):
        """Return the model's message content as a JSON string."""
        request = urllib.request.Request(
            self.endpoint,
            data=json.dumps(self.request_body(messages)).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with self._opener.open(request, timeout=self.timeout) as response:
                raw = response.read(self.max_response_bytes + 1)
        except urllib.error.HTTPError as exc:
            detail = exc.read(2_000).decode("utf-8", "replace")
            raise ModelError(f"Ollama returned HTTP {exc.code}: {detail}") from None
        except OSError as exc:
            raise ModelError(f"cannot reach Ollama at {self.endpoint}: {exc}") from None

        if len(raw) > self.max_response_bytes:
            raise ModelError(f"Ollama response exceeded {self.max_response_bytes} bytes")
        try:
            content = json.loads(raw)["message"]["content"]
        except (ValueError, KeyError, TypeError):
            raise ModelError("Ollama response has no message.content") from None
        if not isinstance(content, str):
            raise ModelError("Ollama message.content is not text")
        return content
