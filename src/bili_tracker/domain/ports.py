from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from bili_tracker.domain.jobs import Artifact, Job
from bili_tracker.domain.models import ManagedModel, ModelAsset

ProgressSink = Callable[[float, str], None]


@dataclass(frozen=True)
class SourceCapabilities:
    can_probe: bool
    can_acquire: bool
    requires_credentials: bool = False
    operations: tuple[str, ...] = ()


@dataclass(frozen=True)
class SourceInput:
    kind: str
    locator: str


@dataclass(frozen=True)
class SourceMetadata:
    canonical_id: str | None
    title: str | None
    duration_seconds: float | None
    display_locator: str


@dataclass(frozen=True)
class AcquiredMedia:
    path: Path
    media_type: str
    source_metadata: SourceMetadata


@dataclass(frozen=True)
class TranscriptionOptions:
    language: str | None = None
    device: str = "auto"


@dataclass(frozen=True)
class TranscriptArtifact:
    text: str
    language: str | None
    model_id: str
    processor_version: str
    artifact: Artifact
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class QualityVerdict:
    passed: bool
    reason_code: str
    details: dict[str, Any]


class SourceAdapter(Protocol):
    id: str

    def capabilities(self) -> SourceCapabilities: ...

    def probe(self, source: SourceInput) -> SourceMetadata: ...

    def acquire(
        self, source: SourceInput, target_dir: Path, progress: ProgressSink
    ) -> AcquiredMedia: ...


class Transcriber(Protocol):
    id: str

    def transcribe(
        self, media: AcquiredMedia, options: TranscriptionOptions, progress: ProgressSink
    ) -> TranscriptArtifact: ...


class TextProcessor(Protocol):
    id: str

    def process(self, text: str, progress: ProgressSink) -> str: ...


class QualityGate(Protocol):
    id: str

    def evaluate(self, original: str, candidate: str) -> QualityVerdict: ...


class Ranker(Protocol):
    id: str

    def rank(self, candidates: Sequence[dict[str, Any]]) -> Sequence[dict[str, Any]]: ...


class ModelRuntime(Protocol):
    id: str

    def deploy(self, asset: ModelAsset, progress: ProgressSink) -> None: ...

    def validate(self, model: ManagedModel) -> QualityVerdict: ...

    def remove(self, model: ManagedModel) -> None: ...


class ArtifactStore(Protocol):
    def write(
        self,
        job: Job,
        kind: str,
        content: bytes,
        media_type: str,
        derived_from: tuple[str, ...] = (),
    ) -> Artifact: ...

    def read(self, artifact: Artifact) -> bytes: ...

    def delete(self, artifact: Artifact) -> None: ...


class JobRepository(Protocol):
    def add(self, job: Job) -> None: ...

    def get(self, job_id: str) -> Job | None: ...

    def claim_next(self) -> Job | None: ...

    def save(self, job: Job) -> None: ...
