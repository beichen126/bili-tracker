from __future__ import annotations

import threading
import uuid
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from bili_tracker import __version__
from bili_tracker.adapters.models.ollama import OllamaRuntime
from bili_tracker.adapters.models.whisper import WhisperRuntime
from bili_tracker.adapters.sources.bilibili import BilibiliClient, BilibiliSource
from bili_tracker.adapters.sources.local_file import LocalFileSource
from bili_tracker.adapters.sources.ytdlp import YtDlpSource
from bili_tracker.adapters.transcribers.whisper import WhisperTranscriber
from bili_tracker.application.discovery import Candidate, QuantitativeRanker
from bili_tracker.application.pipeline import JobRunner
from bili_tracker.config.runtime import RuntimeConfig
from bili_tracker.domain.jobs import ArtifactKind, Job, JobState
from bili_tracker.domain.models import ManagedModel, ModelState
from bili_tracker.domain.ports import SourceAdapter, SourceInput
from bili_tracker.domain.profiles import ProcessingProfile
from bili_tracker.models.manager import ModelManager
from bili_tracker.models.registry import ModelRegistry
from bili_tracker.storage.artifacts import LocalArtifactStore
from bili_tracker.storage.backup import BackupError, BackupManager
from bili_tracker.storage.sqlite import SQLiteJobRepository


class ApiFailure(Exception):
    def __init__(self, code: str, *, status_code: int = 400, retryable: bool = False) -> None:
        self.code = code
        self.status_code = status_code
        self.retryable = retryable
        super().__init__(code)


class SourceBody(BaseModel):
    kind: str
    locator: str = Field(min_length=1, max_length=2_000)


class JobItemBody(BaseModel):
    source: SourceBody
    profile_id: str = Field(default="default", min_length=1, max_length=80)
    run: bool = False


class JobsBody(BaseModel):
    items: list[JobItemBody] = Field(min_length=1, max_length=100)


class LicenseBody(BaseModel):
    accept_license: bool = False


class SettingsBody(BaseModel):
    enable_bilibili: bool | None = None
    enable_remote_text: bool | None = None
    bilibili_cookie: str | None = Field(default=None, max_length=10_000)
    deepseek_api_key: str | None = Field(default=None, max_length=500)


class DiscoveryBody(BaseModel):
    query: str = Field(min_length=1, max_length=100)
    page: int = Field(default=1, ge=1, le=100)
    page_size: int = Field(default=20, ge=1, le=50)


class AppContainer:
    def __init__(self, config: RuntimeConfig, *, registry: ModelRegistry | None = None) -> None:
        self.config = config
        data_dir = config.ensure_data_dir()
        self.repository = SQLiteJobRepository(data_dir / "jobs.sqlite3")
        self.artifacts = LocalArtifactStore(data_dir / "artifacts")
        self.backups = BackupManager(data_dir, self.repository)
        self.model_root = data_dir / "models"
        self.registry = registry or _load_registry()
        self.models = ModelManager(self.registry, self.model_root)
        self.sources: dict[str, SourceAdapter] = {
            "local": LocalFileSource(config.allowed_local_roots),
            "url": YtDlpSource(),
        }
        if config.enable_bilibili:
            self.sources["bilibili"] = BilibiliSource(BilibiliClient())
        self.settings: dict[str, object] = {
            "enable_bilibili": config.enable_bilibili,
            "enable_remote_text": config.enable_remote_text,
            "bilibili_cookie_configured": False,
            "deepseek_api_key_configured": False,
        }
        self.operations: dict[str, threading.Thread] = {}
        self.job_operations: dict[str, str] = {}
        self.model_operations: dict[str, str] = {}
        self._operation_lock = threading.Lock()

    def source(self, kind: str) -> SourceAdapter:
        try:
            return self.sources[kind]
        except KeyError as exc:
            raise ApiFailure("source.unsupported", status_code=422) from exc

    def start_job(self, job_id: str) -> str:
        with self._operation_lock:
            active_id = self.job_operations.get(job_id)
            active_thread = self.operations.get("job:" + active_id) if active_id else None
            if active_thread and active_thread.is_alive():
                return active_id
            job = self.repository.get(job_id)
            if job is None:
                raise ApiFailure("job.not_found", status_code=404)
            if job.state != JobState.QUEUED:
                raise ApiFailure("job.not_runnable", status_code=409)
            operation_id = uuid.uuid4().hex
            thread = threading.Thread(
                target=self._run_job,
                args=(job_id,),
                name=f"bili-tracker-job-{job_id[:8]}",
                daemon=True,
            )
            self.operations["job:" + operation_id] = thread
            self.job_operations[job_id] = operation_id
            thread.start()
            return operation_id

    def _run_job(self, job_id: str) -> None:
        job = self.repository.get(job_id)
        if job is None:
            return
        try:
            source_kind, _ = job.source_ref.split(":", 1)
            source = self.source(source_kind)
            model_path = self.model_root / "whisper-large-v3-turbo.pt"
            if not model_path.is_file():
                job.fail("model.not_ready")
                self.repository.save(job)
                return
            runner = JobRunner(
                self.repository,
                self.artifacts,
                source,
                WhisperTranscriber(model_path),
                ProcessingProfile(job.profile_id),
            )
            runner.run(job)
        except Exception:
            if job.state in {
                JobState.ACQUIRING,
                JobState.TRANSCRIBING,
                JobState.REFINING,
                JobState.REVIEWING,
                JobState.PACKAGING,
            }:
                job.fail("job.worker_failed")
                self.repository.save(job)

    def model(self, model_id: str) -> ManagedModel:
        try:
            asset = self.registry.get(model_id)
        except KeyError as exc:
            raise ApiFailure("model.not_found", status_code=404) from exc
        return self.models._load(asset)


def create_app(
    config: RuntimeConfig | None = None,
    *,
    container: AppContainer | None = None,
) -> FastAPI:
    settings = config or RuntimeConfig.from_env()
    services = container or AppContainer(settings)
    app = FastAPI(title="bili-tracker", version=__version__)
    app.state.container = services

    @app.exception_handler(ApiFailure)
    async def api_failure_handler(_request, exc: ApiFailure):
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": exc.code,
                    "message": _message(exc.code),
                    "request_id": uuid.uuid4().hex,
                    "retryable": exc.retryable,
                    "details": {},
                }
            },
        )

    @app.get("/api/v1/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @app.get("/api/v1/readiness")
    def readiness() -> dict[str, object]:
        return {
            "status": "ready",
            "capabilities": {"local_api": True, "bilibili": bool(services.config.enable_bilibili)},
        }

    @app.get("/api/v1/capabilities")
    def capabilities() -> dict[str, object]:
        return {
            "sources": [
                {"id": key, "capabilities": value.capabilities().__dict__}
                for key, value in services.sources.items()
            ],
            "transcribers": [{"id": "whisper", "optional_dependency": "asr"}],
            "text_processors": [{"id": "ollama", "optional_dependency": "models"}],
            "limits": {"batch_items": 100, "max_local_bytes": 20_000_000_000},
        }

    @app.get("/api/v1/models")
    def models() -> dict[str, object]:
        return {
            "models": [
                _model_dto(services.models, asset.id) for asset in services.registry.all()
            ]
        }

    @app.post("/api/v1/models/{model_id}/install", status_code=202)
    def install_model(model_id: str, body: LicenseBody) -> dict[str, object]:
        model = services.model(model_id)
        if model.state == ModelState.READY and services.models.verify(model_id):
            return {"operation_id": None, "model": _model_dto(services.models, model_id)}
        if not body.accept_license:
            services.models.install(
                model_id, accept_license=False, runtime=_runtime(services, model_id)
            )
            return {"operation_id": None, "model": _model_dto(services.models, model_id)}
        operation_id = uuid.uuid4().hex
        with services._operation_lock:
            active = services.operations.get("model:" + model_id)
            if active and active.is_alive():
                return {
                    "operation_id": services.model_operations.get(model_id),
                    "model": _model_dto(services.models, model_id),
                }
            cancel = threading.Event()
            thread = threading.Thread(
                target=_install_model,
                args=(services, model_id, body.accept_license, cancel),
                name=f"bili-tracker-model-{model_id}",
                daemon=True,
            )
            services.operations["model:" + model_id] = thread
            services.model_operations[model_id] = operation_id
            thread.start()
        return {"operation_id": operation_id, "model": _model_dto(services.models, model_id)}

    @app.post("/api/v1/models/{model_id}/cancel")
    def cancel_model(model_id: str) -> dict[str, object]:
        services.models.cancel(model_id)
        return {"model": _model_dto(services.models, model_id)}

    @app.post("/api/v1/models/{model_id}/verify")
    def verify_model(model_id: str) -> dict[str, object]:
        services.model(model_id)
        return {
            "verified": services.models.verify(model_id),
            "model": _model_dto(services.models, model_id),
        }

    @app.post("/api/v1/models/{model_id}/repair", status_code=202)
    def repair_model(model_id: str, body: LicenseBody) -> dict[str, object]:
        return install_model(model_id, body)

    @app.delete("/api/v1/models/{model_id}")
    def remove_model(model_id: str) -> dict[str, object]:
        try:
            services.models.remove(model_id)
        except RuntimeError as exc:
            raise ApiFailure("model.in_use", status_code=409) from exc
        return {"model": _model_dto(services.models, model_id)}

    @app.post("/api/v1/sources/probe")
    def probe_source(body: SourceBody) -> dict[str, object]:
        source = services.source(body.kind)
        try:
            metadata = source.probe(SourceInput(body.kind, body.locator))
        except Exception as exc:
            code = getattr(exc, "code", "source.probe_failed")
            raise ApiFailure(code, status_code=422) from exc
        return {
            "source": {
                "kind": body.kind,
                "canonical_id": metadata.canonical_id,
                "title": metadata.title,
                "duration_seconds": metadata.duration_seconds,
                "display_locator": metadata.display_locator,
            }
        }

    @app.post("/api/v1/discovery/search")
    def discovery_search(body: DiscoveryBody) -> dict[str, object]:
        source = services.sources.get("bilibili")
        if not isinstance(source, BilibiliSource):
            raise ApiFailure("discovery.disabled", status_code=409)
        try:
            rows = source.client.search(body.query, page=body.page, page_size=body.page_size)
        except Exception as exc:
            raise ApiFailure(getattr(exc, "code", "discovery.failed"), status_code=422) from exc
        candidates = [
            Candidate(
                id=str(row["bvid"]),
                title=str(row["title"]),
                url=str(row["url"]),
                duration_seconds=float(row["duration_seconds"])
                if isinstance(row.get("duration_seconds"), (int, float))
                else None,
                views=int(row.get("views", 0)),
            )
            for row in rows
        ]
        ranked = QuantitativeRanker().rank(candidates, query=body.query)
        return {
            "candidates": [
                {
                    "id": item.id,
                    "title": item.title,
                    "url": item.url,
                    "quantitative_score": item.quantitative_score,
                    "remote_score": item.remote_score,
                    "final_score": item.final_score,
                    "filter_reason": item.filter_reason,
                }
                for item in ranked
            ],
            "ranking_mode": "quantitative",
        }

    @app.post("/api/v1/jobs", status_code=201)
    def create_jobs(body: JobsBody) -> dict[str, object]:
        added: list[dict[str, object]] = []
        rejected: list[dict[str, object]] = []
        duplicates: list[dict[str, object]] = []
        existing = {job.source_ref for job in services.repository.list(limit=1000)}
        for item in body.items:
            source_ref = f"{item.source.kind}:{item.source.locator}"
            if source_ref in existing:
                duplicates.append({"source": _safe_source(item.source.kind, item.source.locator)})
                continue
            try:
                services.source(item.source.kind).probe(
                    SourceInput(item.source.kind, item.source.locator)
                )
                job = Job(source_ref=source_ref, profile_id=item.profile_id)
                services.repository.add(job)
                existing.add(source_ref)
                record: dict[str, object] = {"job_id": str(job.id), "status": job.state.value}
                if item.run:
                    record["operation_id"] = services.start_job(str(job.id))
                added.append(record)
            except Exception as exc:
                rejected.append(
                    {
                        "source": _safe_source(item.source.kind, item.source.locator),
                        "code": getattr(exc, "code", "source.rejected"),
                    }
                )
        return {"added": added, "rejected": rejected, "duplicate": duplicates}

    @app.get("/api/v1/jobs")
    def list_jobs(limit: int = 100) -> dict[str, object]:
        if not 1 <= limit <= 1000:
            raise ApiFailure("job.limit_invalid", status_code=422)
        return {"jobs": [_job_dto(job) for job in services.repository.list(limit)]}

    @app.get("/api/v1/jobs/{job_id}")
    def get_job(job_id: str) -> dict[str, object]:
        return {"job": _job_dto(_job(services, job_id))}

    @app.post("/api/v1/jobs/{job_id}/run", status_code=202)
    def run_job(job_id: str) -> dict[str, object]:
        return {"operation_id": services.start_job(job_id)}

    @app.post("/api/v1/jobs/{job_id}/retry")
    def retry_job(job_id: str) -> dict[str, object]:
        job = _job(services, job_id)
        try:
            job.retry()
        except Exception as exc:
            raise ApiFailure("job.not_retryable", status_code=409) from exc
        services.repository.save(job)
        return {"job": _job_dto(job)}

    @app.post("/api/v1/jobs/{job_id}/cancel")
    def cancel_job(job_id: str) -> dict[str, object]:
        job = _job(services, job_id)
        try:
            job.cancel()
        except Exception as exc:
            raise ApiFailure("job.not_cancellable", status_code=409) from exc
        services.repository.save(job)
        return {"job": _job_dto(job)}

    @app.post("/api/v1/jobs/{job_id}/rebuild")
    def rebuild_job(job_id: str) -> dict[str, object]:
        job = _job(services, job_id)
        try:
            job.rebuild_derived()
        except Exception as exc:
            raise ApiFailure("job.not_rebuildable", status_code=409) from exc
        services.repository.save(job)
        return {"job": _job_dto(job)}

    @app.get("/api/v1/jobs/{job_id}/artifacts/{kind}")
    def get_artifact(job_id: str, kind: str) -> Response:
        job = _job(services, job_id)
        try:
            artifact = job.artifacts[ArtifactKind(kind)]
            content = services.artifacts.read(artifact)
        except (KeyError, ValueError) as exc:
            raise ApiFailure("artifact.not_found", status_code=404) from exc
        return Response(
            content,
            media_type=artifact.media_type,
            headers={"Content-Disposition": f'attachment; filename="{kind}"'},
        )

    @app.get("/api/v1/settings")
    def get_settings() -> dict[str, object]:
        return {"settings": dict(services.settings)}

    @app.patch("/api/v1/settings")
    def patch_settings(body: SettingsBody) -> dict[str, object]:
        values = body.model_dump(exclude_none=True)
        for key in ("enable_bilibili", "enable_remote_text"):
            if key in values:
                services.settings[key] = bool(values[key])
        if body.bilibili_cookie is not None:
            services.settings["bilibili_cookie_configured"] = bool(body.bilibili_cookie)
        if body.deepseek_api_key is not None:
            services.settings["deepseek_api_key_configured"] = bool(body.deepseek_api_key)
        return {"settings": dict(services.settings)}

    @app.post("/api/v1/backups", status_code=201)
    def create_backup() -> dict[str, object]:
        backup_id = f"backup-{uuid.uuid4().hex}.zip"
        destination = services.config.data_dir / "backups" / backup_id
        try:
            services.backups.create(destination)
        except BackupError as exc:
            raise ApiFailure("backup.create_failed", status_code=500) from exc
        return {"backup_id": backup_id, "scope": ["database", "artifacts"]}

    @app.get("/api/v1/backups")
    def list_backups() -> dict[str, object]:
        root = services.config.data_dir / "backups"
        return {
            "backups": [path.name for path in sorted(root.glob("backup-*.zip"))]
            if root.is_dir()
            else []
        }

    @app.post("/api/v1/backups/{backup_id}/validate")
    def validate_backup(backup_id: str) -> dict[str, object]:
        path = _backup_path(services, backup_id)
        try:
            services.backups.validate(path)
        except (BackupError, OSError) as exc:
            raise ApiFailure("backup.invalid", status_code=422) from exc
        return {"backup_id": backup_id, "valid": True}

    @app.post("/api/v1/backups/{backup_id}/restore")
    def restore_backup(backup_id: str) -> dict[str, object]:
        path = _backup_path(services, backup_id)
        try:
            services.backups.restore(path)
        except (BackupError, OSError) as exc:
            raise ApiFailure("backup.restore_failed", status_code=422) from exc
        return {"backup_id": backup_id, "restored": True}

    web_dir = Path(__file__).resolve().parents[1] / "web"
    if web_dir.is_dir():
        app.mount("/", StaticFiles(directory=web_dir, html=True), name="web")
    else:
        @app.get("/", include_in_schema=False)
        def index() -> Response:
            return Response("bili-tracker", media_type="text/plain")
    return app


def _load_registry() -> ModelRegistry:
    directory = Path(__file__).resolve().parents[3] / "model-manifests"
    if not directory.is_dir():
        return ModelRegistry({})
    return ModelRegistry.from_directory(directory)


def _runtime(services: AppContainer, model_id: str):
    asset = services.registry.get(model_id)
    if asset.runtime == "ollama":
        return OllamaRuntime(services.model_root)
    return WhisperRuntime(services.model_root)


def _install_model(
    services: AppContainer, model_id: str, accept: bool, cancel: threading.Event
) -> None:
    try:
        services.models.install(
            model_id,
            accept_license=accept,
            runtime=_runtime(services, model_id),
            cancel_event=cancel,
        )
    except Exception:
        return None


def _model_dto(manager: ModelManager, model_id: str) -> dict[str, object]:
    model = manager._load(manager.registry.get(model_id))
    asset = model.asset
    return {
        "id": asset.id,
        "role": asset.role,
        "version": asset.version,
        "filename": asset.filename,
        "size_bytes": asset.size_bytes,
        "license": {"id": asset.license_id, "url": asset.license_url},
        "runtime": asset.runtime,
        "state": model.state.value,
        "downloaded_bytes": model.downloaded_bytes,
        "progress": min(1.0, model.downloaded_bytes / asset.size_bytes),
        "operation_id": model.operation_id,
        "error_code": model.error_code,
    }


def _job(services: AppContainer, job_id: str) -> Job:
    job = services.repository.get(job_id)
    if job is None:
        raise ApiFailure("job.not_found", status_code=404)
    return job


def _job_dto(job: Job) -> dict[str, object]:
    kind, locator = job.source_ref.partition(":")
    return {
        "id": str(job.id),
        "state": job.state.value,
        "source": _safe_source(kind, locator),
        "profile_id": job.profile_id,
        "attempts": job.attempts,
        "error_code": job.error_code,
        "degraded": job.degraded,
        "created_at": job.created_at.isoformat(),
        "updated_at": job.updated_at.isoformat(),
        "artifacts": [
            {"kind": artifact.kind.value, "media_type": artifact.media_type}
            for artifact in job.artifacts.values()
        ],
    }


def _safe_source(kind: str, locator: str) -> dict[str, str]:
    if kind == "local":
        return {"kind": kind, "display_locator": Path(locator).name}
    if kind in {"url", "bilibili"}:
        parsed = urlparse(locator)
        return {
            "kind": kind,
            "display_locator": f"{parsed.hostname or 'url'}{parsed.path[:160]}",
        }
    return {"kind": kind or "unknown", "display_locator": "redacted"}


def _backup_path(services: AppContainer, backup_id: str) -> Path:
    if not backup_id.startswith("backup-") or Path(backup_id).name != backup_id:
        raise ApiFailure("backup.not_found", status_code=404)
    path = services.config.data_dir / "backups" / backup_id
    if not path.is_file():
        raise ApiFailure("backup.not_found", status_code=404)
    return path


def _message(code: str) -> str:
    return {
        "source.unsupported": "该来源适配器未启用。",
        "source.probe_failed": "来源解析失败。",
        "job.not_found": "任务不存在。",
        "model.not_found": "模型不存在。",
        "model.not_ready": "所需模型尚未准备完成。",
        "backup.not_found": "备份不存在。",
    }.get(code, "请求未能完成。")
