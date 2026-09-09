from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProcessingProfile:
    id: str
    transcriber_id: str = "whisper"
    language: str | None = None
    text_processor_id: str | None = None
    quality_policy: str = "deterministic"
    post_process_failure: str = "preserve_raw"

    def __post_init__(self) -> None:
        if self.post_process_failure not in {"preserve_raw", "fail_job"}:
            raise ValueError("post_process_failure must be preserve_raw or fail_job")
