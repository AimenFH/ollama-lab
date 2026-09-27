"""Local Ollama chat adapter."""


class OllamaModel:
    """Callable adapter for Ollama's local chat endpoint."""

    def __init__(self, model_name, endpoint="http://127.0.0.1:11434/api/chat"):
        self.model_name = model_name
        self.endpoint = endpoint

    def __call__(self, messages):
        """Return the model's message content as a JSON string."""
        # TODO Checkpoint 2: POST the bounded JSON request described in the handout.
        raise NotImplementedError("Complete the Ollama request")
