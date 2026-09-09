from unittest.mock import patch

import pytest

from bili_tracker.adapters.text.ollama import OllamaTextProcessor, split_text
from bili_tracker.adapters.text.quality import DeterministicQualityGate


def test_split_text_handles_unicode_and_boundaries():
    chunks = split_text("第一段。第二段。第三段。", max_chars=6)
    assert "" not in chunks
    assert "".join(chunks).replace("\n", "") == "第一段。第二段。第三段。"


def test_remote_processor_requires_explicit_opt_in():
    with pytest.raises(ValueError):
        OllamaTextProcessor(base_url="https://remote.example")


def test_quality_gate_rejects_empty_and_accepts_reasonable_output():
    gate = DeterministicQualityGate()
    assert gate.evaluate("source text", "").passed is False
    assert gate.evaluate("source text", "source text cleaned").passed is True


def test_ollama_processor_parses_local_chat_response():
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b'{"message":{"content":"cleaned"}}'

    progress = []
    with patch("urllib.request.urlopen", return_value=Response()):
        output = OllamaTextProcessor(max_chars=10).process(
            "source text", lambda value, stage: progress.append((value, stage))
        )
    assert output == "cleaned\n\ncleaned"
    assert progress[-1] == (1.0, "refining")
