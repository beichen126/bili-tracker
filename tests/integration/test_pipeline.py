from pathlib import Path

from bili_tracker.application.pipeline import JobRunner
from bili_tracker.domain.jobs import Artifact, ArtifactKind, Job
from bili_tracker.domain.ports import (
    AcquiredMedia,
    QualityGate,
    QualityVerdict,
    SourceCapabilities,
    SourceMetadata,
    TextProcessor,
    Transcriber,
    TranscriptArtifact,
)
from bili_tracker.domain.profiles import ProcessingProfile
from bili_tracker.storage.artifacts import LocalArtifactStore
from bili_tracker.storage.sqlite import SQLiteJobRepository


class FakeSource:
    id = "fake"

    def capabilities(self):
        return SourceCapabilities(True, True)

    def probe(self, source):
        return SourceMetadata(None, None, None, source.locator)

    def acquire(self, source, target_dir, progress):
        path = target_dir / "audio.wav"
        path.write_bytes(b"audio")
        return AcquiredMedia(path, "audio/wav", self.probe(source))


class FakeTranscriber(Transcriber):
    id = "fake"

    def transcribe(self, media, options, progress):
        artifact = Artifact(ArtifactKind.RAW, "", "", "text/plain")
        return TranscriptArtifact(
            "raw transcript", options.language, "fake-model", "test", artifact
        )


class FailingProcessor(TextProcessor):
    id = "failing"

    def process(self, text, progress):
        raise RuntimeError("text.processor_unavailable")


class UpperProcessor(TextProcessor):
    id = "upper"

    def process(self, text, progress):
        return text.upper()


class PassingGate(QualityGate):
    id = "pass"

    def evaluate(self, original, candidate):
        return QualityVerdict(True, "ok", {})


def runner(tmp_path: Path, profile: ProcessingProfile, processor=None):
    repo = SQLiteJobRepository(tmp_path / "app.sqlite3")
    store = LocalArtifactStore(tmp_path / "artifacts")
    return repo, JobRunner(
        repo, store, FakeSource(), FakeTranscriber(), profile, processor, PassingGate()
    )


def test_local_pipeline_preserves_raw_and_builds_final(tmp_path: Path):
    repo, run = runner(tmp_path, ProcessingProfile("default"))
    job = Job(source_ref="local:test.wav")
    repo.add(job)
    result = run.run(job)
    assert result.job.state.value == "completed"
    assert set(result.job.artifacts) == {ArtifactKind.RAW, ArtifactKind.FINAL}
    assert result.job.degraded is False


def test_processor_failure_preserves_raw_as_degraded_final(tmp_path: Path):
    profile = ProcessingProfile("default", post_process_failure="preserve_raw")
    repo, run = runner(tmp_path, profile, FailingProcessor())
    job = Job(source_ref="local:test.wav")
    repo.add(job)
    result = run.run(job)
    assert result.job.state.value == "completed"
    assert result.job.degraded is True
    assert set(result.job.artifacts) == {ArtifactKind.RAW, ArtifactKind.FINAL}


def test_processor_failure_fail_job_is_stable(tmp_path: Path):
    profile = ProcessingProfile("default", post_process_failure="fail_job")
    repo, run = runner(tmp_path, profile, FailingProcessor())
    job = Job(source_ref="local:test.wav")
    repo.add(job)
    result = run.run(job)
    assert result.job.state.value == "failed"
    assert ArtifactKind.RAW in result.job.artifacts
