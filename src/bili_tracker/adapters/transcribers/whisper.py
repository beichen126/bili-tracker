from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic
from typing import Any

from bili_tracker.domain.jobs import Artifact, ArtifactKind
from bili_tracker.domain.ports import (
    AcquiredMedia,
    ProgressSink,
    Transcriber,
    TranscriptArtifact,
    TranscriptionOptions,
)


class WhisperTranscriber(Transcriber):
    id = "whisper"

    def __init__(
        self,
        model_path: Path,
        model_id: str = "whisper-large-v3-turbo",
        loader: Callable[[Path, str], Any] | None = None,
    ) -> None:
        self.model_path = model_path.expanduser().resolve()
        self.model_id = model_id
        self._loader = loader
        self._model: Any | None = None

    def capabilities(self) -> dict[str, object]:
        return {"languages": "whisper", "devices": ["auto", "cpu", "cuda"]}

    def _load(self, device: str) -> Any:
        if self._model is not None:
            return self._model
        if self._loader:
            self._model = self._loader(self.model_path, device)
            return self._model
        try:
            import whisper
        except ImportError as exc:
            raise RuntimeError("transcriber.runtime_missing") from exc
        self._model = whisper.load_model(str(self.model_path), device=device)
        return self._model

    def transcribe(
        self,
        media: AcquiredMedia,
        options: TranscriptionOptions,
        progress: ProgressSink,
    ) -> TranscriptArtifact:
        started = monotonic()
        device = options.device
        if device == "auto":
            try:
                import torch

                device = "cuda" if torch.cuda.is_available() else "cpu"
            except ImportError:
                device = "cpu"
        progress(0.0, "loading")
        model = self._load(device)
        kwargs: dict[str, object] = {}
        if options.language:
            kwargs["language"] = options.language
        result = model.transcribe(str(media.path), **kwargs)
        text = str(result.get("text", "")).strip()
        if not text:
            raise RuntimeError("transcriber.empty_output")
        progress(1.0, "completed")
        artifact = Artifact(
            kind=ArtifactKind.RAW,
            relative_path="",
            sha256="",
            media_type="text/plain",
        )
        return TranscriptArtifact(
            text,
            options.language,
            self.model_id,
            "whisper",
            artifact,
            metadata={
                "device": device,
                "language": options.language,
                "started_at": datetime.now(UTC).isoformat(),
                "elapsed_seconds": round(monotonic() - started, 3),
            },
        )
