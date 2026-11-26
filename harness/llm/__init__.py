"""LLM adapter interface. An adapter is any class with `model` and `chat(messages, tools)`."""


class LLMError(RuntimeError):
    """`recoverable=True` means the model produced unusable output (e.g. malformed tool JSON): the loop tells
    the model and retries instead of abandoning the task."""

    def __init__(self, message: str, recoverable: bool = False):
        super().__init__(message)
        self.recoverable = recoverable
