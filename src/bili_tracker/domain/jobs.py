from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from bili_tracker.domain.errors import InvalidTransition, InvariantViolation


def utc_now() -> datetime:
    return datetime.now(UTC)


class JobState(StrEnum):
    QUEUED = "queued"
    ACQUIRING = "acquiring"
    TRANSCRIBING = "transcribing"
    REFINING = "refining"
    REVIEWING = "reviewing"
    PACKAGING = "packaging"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ArtifactKind(StrEnum):
    RAW = "raw"
    REFINED = "refined"
    FINAL = "final"


_TRANSITIONS: dict[JobState, frozenset[JobState]] = {
    JobState.QUEUED: frozenset({JobState.ACQUIRING, JobState.CANCELLED}),
    JobState.ACQUIRING: frozenset({JobState.TRANSCRIBING, JobState.FAILED, JobState.CANCELLED}),
    JobState.TRANSCRIBING: frozenset(
        {JobState.REFINING, JobState.PACKAGING, JobState.FAILED, JobState.CANCELLED}
    ),
    JobState.REFINING: frozenset(
        {JobState.REVIEWING, JobState.PACKAGING, JobState.FAILED, JobState.CANCELLED}
    ),
    JobState.REVIEWING: frozenset(
        {JobState.REFINING, JobState.PACKAGING, JobState.FAILED, JobState.CANCELLED}
    ),
    JobState.PACKAGING: frozenset({JobState.COMPLETED, JobState.FAILED, JobState.CANCELLED}),
    JobState.COMPLETED: frozenset({JobState.REFINING}),
    JobState.FAILED: frozenset({JobState.QUEUED}),
    JobState.CANCELLED: frozenset({JobState.QUEUED}),
}


@dataclass(frozen=True)
class Artifact:
    kind: ArtifactKind
    relative_path: str
    sha256: str
    media_type: str
    derived_from: tuple[str, ...] = ()


@dataclass
class Job:
    id: UUID = field(default_factory=uuid4)
    schema_version: int = 1
    state: JobState = JobState.QUEUED
    source_ref: str = ""
    profile_id: str = "default"
    attempts: int = 0
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    error_code: str | None = None
    degraded: bool = False
    artifacts: dict[ArtifactKind, Artifact] = field(default_factory=dict)

    def transition(self, target: JobState) -> None:
        if target not in _TRANSITIONS[self.state]:
            raise InvalidTransition("job", self.state.value, target.value)
        self.state = target
        self.updated_at = utc_now()

    def begin_attempt(self) -> None:
        if self.state != JobState.QUEUED:
            raise InvalidTransition("job", self.state.value, JobState.ACQUIRING.value)
        self.attempts += 1
        self.error_code = None
        self.transition(JobState.ACQUIRING)

    def fail(self, error_code: str) -> None:
        if not error_code or "." not in error_code:
            raise InvariantViolation(
                "job.error_code_required", "failed jobs require a stable error code"
            )
        if JobState.FAILED not in _TRANSITIONS[self.state]:
            raise InvalidTransition("job", self.state.value, JobState.FAILED.value)
        self.error_code = error_code
        self.transition(JobState.FAILED)

    def cancel(self) -> None:
        self.transition(JobState.CANCELLED)

    def retry(self) -> None:
        self.transition(JobState.QUEUED)
        self.error_code = None

    def add_artifact(self, artifact: Artifact) -> None:
        if artifact.kind in self.artifacts:
            raise InvariantViolation(
                "artifact.duplicate", f"artifact already exists: {artifact.kind.value}"
            )
        path_parts = artifact.relative_path.replace("\\", "/").split("/")
        if artifact.relative_path.startswith(("/", "\\")) or ".." in path_parts:
            raise InvariantViolation(
                "artifact.path_invalid", "artifact path must be relative and contained"
            )
        self.artifacts[artifact.kind] = artifact
        self.updated_at = utc_now()

    def complete(self, *, degraded: bool = False) -> None:
        if self.state != JobState.PACKAGING:
            raise InvalidTransition("job", self.state.value, JobState.COMPLETED.value)
        required = {ArtifactKind.RAW, ArtifactKind.FINAL}
        if not required.issubset(self.artifacts):
            missing = ",".join(sorted(kind.value for kind in required - self.artifacts.keys()))
            raise InvariantViolation(
                "job.required_artifact_missing", f"missing required artifacts: {missing}"
            )
        self.degraded = degraded
        self.transition(JobState.COMPLETED)

    def rebuild_derived(self) -> None:
        if self.state != JobState.COMPLETED:
            raise InvalidTransition("job", self.state.value, JobState.REFINING.value)
        self.artifacts.pop(ArtifactKind.REFINED, None)
        self.artifacts.pop(ArtifactKind.FINAL, None)
        self.degraded = False
        self.transition(JobState.REFINING)

    def has_artifacts(self, kinds: Iterable[ArtifactKind]) -> bool:
        return set(kinds).issubset(self.artifacts)
