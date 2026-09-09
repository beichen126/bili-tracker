from __future__ import annotations

from dataclasses import dataclass

from bili_tracker.domain.jobs import ArtifactKind, Job, JobState
from bili_tracker.domain.ports import (
    AcquiredMedia,
    QualityGate,
    SourceAdapter,
    SourceInput,
    TextProcessor,
    Transcriber,
    TranscriptionOptions,
)
from bili_tracker.domain.profiles import ProcessingProfile
from bili_tracker.storage.artifacts import LocalArtifactStore
from bili_tracker.storage.sqlite import SQLiteJobRepository


@dataclass(frozen=True)
class PipelineResult:
    job: Job
    media: AcquiredMedia | None = None


class JobRunner:
    def __init__(
        self,
        repository: SQLiteJobRepository,
        artifact_store: LocalArtifactStore,
        source: SourceAdapter,
        transcriber: Transcriber,
        profile: ProcessingProfile,
        text_processor: TextProcessor | None = None,
        quality_gate: QualityGate | None = None,
    ) -> None:
        self.repository = repository
        self.artifact_store = artifact_store
        self.source = source
        self.transcriber = transcriber
        self.profile = profile
        self.text_processor = text_processor
        self.quality_gate = quality_gate

    def run(self, job: Job) -> PipelineResult:
        media: AcquiredMedia | None = None
        try:
            if job.state == JobState.QUEUED:
                job.begin_attempt()
            if job.state != JobState.ACQUIRING:
                raise RuntimeError("pipeline.invalid_start_state")
            self.repository.save(job)
            if not job.has_artifacts([ArtifactKind.RAW]):
                source = self._source_input(job.source_ref)
                work_dir = self.artifact_store.job_dir(str(job.id)) / "work"
                work_dir.mkdir(parents=True, exist_ok=True)
                media = self.source.acquire(source, work_dir, lambda _value, _stage: None)
                job.transition(JobState.TRANSCRIBING)
                self.repository.save(job)
                transcript = self.transcriber.transcribe(
                    media,
                    TranscriptionOptions(language=self.profile.language),
                    lambda _value, _stage: None,
                )
                raw = self.artifact_store.write(
                    job, ArtifactKind.RAW.value, transcript.text.encode("utf-8"), "text/plain"
                )
                job.add_artifact(raw)
                self.repository.save(job)
                raw_text = transcript.text
            else:
                raw_text = self.artifact_store.read(job.artifacts[ArtifactKind.RAW]).decode("utf-8")
            if not self.text_processor:
                job.transition(JobState.PACKAGING)
                final = self.artifact_store.write(
                    job, ArtifactKind.FINAL.value, raw_text.encode("utf-8"), "text/markdown"
                )
                job.add_artifact(final)
                job.complete()
                self.repository.save(job)
                return PipelineResult(job, media)
            job.transition(JobState.REFINING)
            self.repository.save(job)
            try:
                refined_text = self.text_processor.process(raw_text, lambda _value, _stage: None)
            except Exception as exc:
                code = getattr(exc, "code", None) or str(exc)
                if "." not in code:
                    code = "text.processor_failed"
                return self._post_process_failure(job, raw_text, code, media)
            refined = self.artifact_store.write(
                job, ArtifactKind.REFINED.value, refined_text.encode("utf-8"), "text/markdown"
            )
            job.add_artifact(refined)
            if self.quality_gate:
                job.transition(JobState.REVIEWING)
                self.repository.save(job)
                verdict = self.quality_gate.evaluate(raw_text, refined_text)
                if not verdict.passed:
                    return self._post_process_failure(job, raw_text, "quality.rejected", media)
            job.transition(JobState.PACKAGING)
            final = self.artifact_store.write(
                job, ArtifactKind.FINAL.value, refined_text.encode("utf-8"), "text/markdown"
            )
            job.add_artifact(final)
            job.complete()
            self.repository.save(job)
            return PipelineResult(job, media)
        except Exception as exc:
            code = getattr(exc, "code", None) or str(exc)
            if "." not in code:
                code = "pipeline.stage_failed"
            if job.state in {
                JobState.ACQUIRING,
                JobState.TRANSCRIBING,
                JobState.REFINING,
                JobState.REVIEWING,
                JobState.PACKAGING,
            }:
                job.fail(code)
                self.repository.save(job)
            return PipelineResult(job, media)

    def _post_process_failure(
        self, job: Job, raw_text: str, code: str, media: AcquiredMedia | None
    ) -> PipelineResult:
        if self.profile.post_process_failure == "fail_job":
            job.fail(code)
            self.repository.save(job)
            return PipelineResult(job, media)
        job.transition(JobState.PACKAGING)
        final = self.artifact_store.write(
            job, ArtifactKind.FINAL.value, raw_text.encode("utf-8"), "text/markdown"
        )
        job.add_artifact(final)
        job.complete(degraded=True)
        self.repository.save(job)
        return PipelineResult(job, media)

    @staticmethod
    def _source_input(source_ref: str) -> SourceInput:
        kind, separator, locator = source_ref.partition(":")
        if not separator or not kind or not locator:
            raise RuntimeError("source.invalid")
        return SourceInput(kind, locator)
