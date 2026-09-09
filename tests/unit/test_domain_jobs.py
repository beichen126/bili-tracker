import pytest

from bili_tracker.domain.errors import InvalidTransition, InvariantViolation
from bili_tracker.domain.jobs import Artifact, ArtifactKind, Job, JobState


def artifact(kind: ArtifactKind) -> Artifact:
    return Artifact(kind, f"{kind.value}.txt", "a" * 64, "text/plain")


def test_job_happy_path_requires_raw_and_final():
    job = Job(source_ref="local:test.wav")
    job.begin_attempt()
    job.transition(JobState.TRANSCRIBING)
    job.add_artifact(artifact(ArtifactKind.RAW))
    job.transition(JobState.PACKAGING)
    with pytest.raises(InvariantViolation) as exc:
        job.complete()
    assert exc.value.code == "job.required_artifact_missing"
    job.add_artifact(artifact(ArtifactKind.FINAL))
    job.complete()
    assert job.state == JobState.COMPLETED


def test_invalid_transition_and_retry_are_explicit():
    job = Job(source_ref="local:test.wav")
    with pytest.raises(InvalidTransition):
        job.transition(JobState.COMPLETED)
    job.begin_attempt()
    job.fail("source.unavailable")
    job.retry()
    assert job.state == JobState.QUEUED
    assert job.attempts == 1


def test_preserve_raw_degraded_completion_is_visible():
    job = Job(source_ref="local:test.wav")
    job.begin_attempt()
    job.transition(JobState.TRANSCRIBING)
    job.add_artifact(artifact(ArtifactKind.RAW))
    job.transition(JobState.REFINING)
    job.fail("text.processor_unavailable")
    job.retry()
    job.begin_attempt()
    job.transition(JobState.TRANSCRIBING)
    job.add_artifact(artifact(ArtifactKind.FINAL))
    job.transition(JobState.PACKAGING)
    job.complete(degraded=True)
    assert job.degraded is True


def test_cancelled_job_can_only_be_explicitly_requeued():
    job = Job(source_ref="local:test.wav")
    job.cancel()
    assert job.state == JobState.CANCELLED
    with pytest.raises(InvalidTransition):
        job.transition(JobState.COMPLETED)
    job.retry()
    assert job.state == JobState.QUEUED
