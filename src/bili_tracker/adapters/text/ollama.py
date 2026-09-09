from __future__ import annotations

import json
import urllib.error
import urllib.request
from urllib.parse import urlparse

from bili_tracker.domain.ports import ProgressSink, TextProcessor


def split_text(text: str, max_chars: int = 6000) -> list[str]:
    if max_chars < 1:
        raise ValueError("max_chars must be positive")
    text = text.strip()
    chunks: list[str] = []
    while text:
        if len(text) <= max_chars:
            chunks.append(text)
            break
        boundary = max(
            text.rfind("\n", 0, max_chars),
            text.rfind("。", 0, max_chars),
            text.rfind(".", 0, max_chars),
            text.rfind("！", 0, max_chars),
            text.rfind("?", 0, max_chars),
        )
        cut = boundary if boundary >= max_chars // 2 else max_chars
        chunks.append(text[:cut].strip())
        text = text[cut:].strip()
    return [chunk for chunk in chunks if chunk]


class OllamaTextProcessor(TextProcessor):
    id = "ollama"

    def __init__(
        self,
        model: str = "bili-tracker-qwen3.5-4b-q6k",
        base_url: str = "http://127.0.0.1:11434",
        max_chars: int = 6000,
        timeout: float = 60.0,
        allow_remote: bool = False,
    ) -> None:
        parsed = urlparse(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("text processor URL must be an HTTP(S) URL")
        if not allow_remote and parsed.hostname not in {"127.0.0.1", "::1", "localhost"}:
            raise ValueError("remote text processing must be explicitly enabled")
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.max_chars = max_chars
        self.timeout = timeout

    def process(self, text: str, progress: ProgressSink) -> str:
        chunks = split_text(text, self.max_chars)
        outputs: list[str] = []
        for index, chunk in enumerate(chunks, start=1):
            outputs.append(self._call(chunk))
            progress(index / len(chunks), "refining")
        return "\n\n".join(outputs).strip()

    def _call(self, chunk: str) -> str:
        payload = {
            "model": self.model,
            "stream": False,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Clean transcription punctuation and paragraphs without adding facts."
                    ),
                },
                {"role": "user", "content": chunk},
            ],
        }
        request = urllib.request.Request(
            f"{self.base_url}/api/chat",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
            raise RuntimeError("text.processor_unavailable") from exc
        content = body.get("message", {}).get("content") or body.get("response")
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError("text.processor_empty_output")
        return content.strip()
