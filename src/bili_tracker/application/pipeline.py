from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

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
        transcript_meta: dict[str, object] = {}
        try:
            if job.state == JobState.QUEUED:
                job.begin_attempt()
            if job.state not in {JobState.ACQUIRING, JobState.REFINING}:
                raise RuntimeError("pipeline.invalid_start_state")
            self.repository.save(job)
            if not job.has_artifacts([ArtifactKind.RAW]):
                if job.state != JobState.ACQUIRING:
                    raise RuntimeError("pipeline.raw_required_for_rebuild")
                source = self._source_input(job.source_ref)
                work_dir = self.artifact_store.job_dir(str(job.id)) / "work"
                work_dir.mkdir(parents=True, exist_ok=True)
                media = self.source.acquire(
                    source,
                    work_dir,
                    lambda value, _stage: self._report_progress(job, 0.0, 0.2, value),
                )
                job.transition(JobState.TRANSCRIBING)
                self.repository.save(job)
                transcript = self.transcriber.transcribe(
                    media,
                    TranscriptionOptions(language=self.profile.language),
                    lambda value, _stage: self._report_progress(job, 0.2, 0.6, value),
                )
                transcript_meta = {
                    "transcriber_id": self.transcriber.id,
                    **dict(transcript.metadata),
                    "model_id": transcript.model_id,
                    "processor_version": transcript.processor_version,
                }
                raw = self.artifact_store.write(
                    job, ArtifactKind.RAW.value, transcript.text.encode("utf-8"), "text/plain"
                )
                job.add_artifact(raw)
                self.repository.save(job)
                raw_text = transcript.text
            else:
                raw_text = self.artifact_store.read(job.artifacts[ArtifactKind.RAW]).decode("utf-8")
                if job.state == JobState.ACQUIRING:
                    job.transition(JobState.TRANSCRIBING)
            if not self.text_processor:
                if job.state != JobState.PACKAGING:
                    job.transition(JobState.PACKAGING)
                final = self.artifact_store.write(
                    job,
                    ArtifactKind.FINAL.value,
                    raw_text.encode("utf-8"),
                    "text/markdown",
                    (job.artifacts[ArtifactKind.RAW].relative_path,),
                )
                job.add_artifact(final)
                job.complete()
                self._write_manifest(job, media, transcript_meta=transcript_meta)
                self.repository.save(job)
                return PipelineResult(job, media)
            if job.state != JobState.REFINING:
                job.transition(JobState.REFINING)
            self.repository.save(job)
            try:
                refined_text = self.text_processor.process(
                    raw_text,
                    lambda value, _stage: self._report_progress(job, 0.8, 0.15, value),
                )
            except Exception as exc:
                code = getattr(exc, "code", None) or str(exc)
                if "." not in code:
                    code = "text.processor_failed"
                return self._post_process_failure(job, raw_text, code, media, transcript_meta)
            refined = self.artifact_store.write(
                job,
                ArtifactKind.REFINED.value,
                refined_text.encode("utf-8"),
                "text/markdown",
                (job.artifacts[ArtifactKind.RAW].relative_path,),
            )
            job.add_artifact(refined)
            if self.quality_gate:
                job.transition(JobState.REVIEWING)
                self.repository.save(job)
                verdict = self.quality_gate.evaluate(raw_text, refined_text)
                if not verdict.passed:
                    return self._post_process_failure(
                        job, raw_text, "quality.rejected", media, transcript_meta
                    )
            job.transition(JobState.PACKAGING)
            final = self.artifact_store.write(
                job,
                ArtifactKind.FINAL.value,
                refined_text.encode("utf-8"),
                "text/markdown",
                (refined.relative_path,),
            )
            job.add_artifact(final)
            job.complete()
            self._write_manifest(
                job,
                media,
                transcript_meta={**transcript_meta, "processor_id": self.text_processor.id},
            )
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
                try:
                    self._write_manifest(job, media, transcript_meta, error_code=code)
                except Exception:
                    pass
                self.repository.save(job)
            return PipelineResult(job, media)

    def _post_process_failure(
        self,
        job: Job,
        raw_text: str,
        code: str,
        media: AcquiredMedia | None,
        transcript_meta: dict[str, object],
    ) -> PipelineResult:
        if self.profile.post_process_failure == "fail_job":
            job.fail(code)
            self._write_manifest(job, media, transcript_meta, error_code=code)
            self.repository.save(job)
            return PipelineResult(job, media)
        job.transition(JobState.PACKAGING)
        final = self.artifact_store.write(
            job,
            ArtifactKind.FINAL.value,
            raw_text.encode("utf-8"),
            "text/markdown",
            (job.artifacts[ArtifactKind.RAW].relative_path,),
        )
        job.add_artifact(final)
        job.complete(degraded=True)
        self._write_manifest(job, media, transcript_meta, error_code=code, degraded=True)
        self.repository.save(job)
        return PipelineResult(job, media)

    @staticmethod
    def _source_input(source_ref: str) -> SourceInput:
        kind, separator, locator = source_ref.partition(":")
        if not separator or not kind or not locator:
            raise RuntimeError("source.invalid")
        return SourceInput(kind, locator)

    def _report_progress(self, job: Job, offset: float, span: float, value: float) -> None:
        job.set_progress(offset + span * min(1.0, max(0.0, value)))
        self.repository.save(job)

    def _write_manifest(
        self,
        job: Job,
        media: AcquiredMedia | None,
        transcript_meta: dict[str, object],
        *,
        error_code: str | None = None,
        degraded: bool = False,
    ) -> None:
        kind, _, locator = job.source_ref.partition(":")
        source_metadata = media.source_metadata if media else None
        display_locator = _display_locator(
            kind, source_metadata.display_locator if source_metadata else locator
        )
        canonical_id = source_metadata.canonical_id if source_metadata else None
        if kind == "local":
            canonical_id = None
        previous = job.artifacts.get(ArtifactKind.MANIFEST)
        if not transcript_meta and previous:
            try:
                previous_payload = json.loads(self.artifact_store.read(previous))
                previous_processing = previous_payload.get("processing", {})
                if isinstance(previous_processing, dict):
                    transcript_meta = dict(previous_processing)
            except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError):
                pass
        payload = {
            "format": "bili-tracker-job-manifest",
            "version": 1,
            "job_id": str(job.id),
            "job_schema_version": job.schema_version,
            "state": job.state.value,
            "source": {
                "kind": kind,
                "canonical_id": canonical_id,
                "display_locator": display_locator,
            },
            "profile_id": job.profile_id,
            "processing": transcript_meta,
            "artifacts": {
                artifact.kind.value: {
                    "relative_path": artifact.relative_path,
                    "sha256": artifact.sha256,
                    "media_type": artifact.media_type,
                    "derived_from": list(artifact.derived_from),
                }
                for artifact in job.artifacts.values()
                if artifact.kind != ArtifactKind.MANIFEST
            },
            "error_code": error_code,
            "degraded": degraded,
        }
        if previous:
            try:
                self.artifact_store.delete(previous)
            except FileNotFoundError:
                pass
            job.remove_artifact(ArtifactKind.MANIFEST)
        manifest = self.artifact_store.write(
            job,
            ArtifactKind.MANIFEST.value,
            json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"),
            "application/json",
        )
        job.add_artifact(manifest)


def _display_locator(kind: str, locator: str) -> str:
    if kind == "local":
        return Path(locator).name
    if kind in {"url", "bilibili"}:
        parsed = urlparse(locator)
        return f"{parsed.hostname or 'url'}{parsed.path[:160]}"
    return "redacted"
