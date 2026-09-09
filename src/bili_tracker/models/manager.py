from __future__ import annotations

import json
import os
import shutil
import threading
import uuid
from pathlib import Path

from bili_tracker.domain.models import ManagedModel, ModelAsset, ModelState
from bili_tracker.domain.ports import ModelRuntime, ProgressSink
from bili_tracker.models.downloader import DownloadCancelled, DownloadError, ResumableDownloader
from bili_tracker.models.registry import ModelRegistry


class ModelConflict(RuntimeError):
    code = "model.in_use"


class ModelManager:
    def __init__(
        self,
        registry: ModelRegistry,
        model_root: Path,
        state_path: Path | None = None,
        downloader: ResumableDownloader | None = None,
    ) -> None:
        self.registry = registry
        self.model_root = model_root.expanduser().resolve()
        self.model_root.mkdir(parents=True, exist_ok=True)
        self.state_path = (state_path or self.model_root / "model-state.json").resolve()
        self.downloader = downloader or ResumableDownloader()
        self._lock = threading.RLock()
        self._cancel_events: dict[str, threading.Event] = {}

    def install(
        self,
        model_id: str,
        *,
        accept_license: bool,
        runtime: ModelRuntime,
        progress: ProgressSink | None = None,
        cancel_event: threading.Event | None = None,
    ) -> ManagedModel:
        with self._lock:
            asset = self.registry.get(model_id)
            model = self._load(asset)
            if model.state == ModelState.READY and self.verify(model_id):
                return model
            if model.state == ModelState.READY:
                model.transition(ModelState.CHECKING)
            if model.state == ModelState.NOT_INSTALLED:
                model.transition(ModelState.CHECKING)
            if not accept_license:
                if model.state == ModelState.CHECKING:
                    model.transition(ModelState.AWAITING_LICENSE)
                self._save(model)
                return model
            available = shutil.disk_usage(self.model_root).free
            if available < asset.size_bytes:
                if model.state == ModelState.CHECKING:
                    model.transition(ModelState.AWAITING_LICENSE)
                if model.state == ModelState.AWAITING_LICENSE:
                    model.transition(ModelState.BLOCKED)
                model.error_code = "model.disk_space_insufficient"
                self._save(model)
                return model
            if model.state == ModelState.AWAITING_LICENSE:
                model.transition(ModelState.DOWNLOADING)
            elif model.state == ModelState.CHECKING:
                model.transition(ModelState.AWAITING_LICENSE)
                model.transition(ModelState.DOWNLOADING)
            elif model.state in {ModelState.BLOCKED, ModelState.FAILED}:
                model.transition(ModelState.CHECKING)
                model.transition(ModelState.AWAITING_LICENSE)
                model.transition(ModelState.DOWNLOADING)
            elif model.state != ModelState.DOWNLOADING:
                model.transition(ModelState.DOWNLOADING)
            model.operation_id = model.operation_id or uuid.uuid4().hex
            active_cancel = cancel_event or threading.Event()
            self._cancel_events[model_id] = active_cancel
            self._save(model)
            try:
                result = self.downloader.download(
                    asset,
                    self.model_root,
                    progress=lambda done, total: self._progress(model, done, total, progress),
                    cancel_event=active_cancel,
                )
            except DownloadCancelled as exc:
                model.transition(ModelState.PAUSED)
                model.error_code = exc.code
                self._save(model)
                return model
            except DownloadError as exc:
                model.transition(ModelState.FAILED)
                model.error_code = exc.code
                self._save(model)
                return model
            model.downloaded_bytes = result.path.stat().st_size
            model.transition(ModelState.VERIFYING)
            self._save(model)
            if not self.verify(model_id):
                model.transition(ModelState.FAILED)
                model.error_code = "model.hash_mismatch"
                self._save(model)
                return model
            model.transition(ModelState.DEPLOYING)
            try:
                runtime.deploy(asset, progress or (lambda _value, _message: None))
            except Exception as exc:
                model.transition(ModelState.FAILED)
                model.error_code = getattr(exc, "code", None) or "model.runtime_deploy_failed"
                self._save(model)
                return model
            model.transition(ModelState.VALIDATING)
            try:
                verdict = runtime.validate(model)
            except Exception as exc:
                model.transition(ModelState.FAILED)
                model.error_code = getattr(exc, "code", None) or "model.runtime_validation_failed"
                self._save(model)
                return model
            if not verdict.passed:
                model.transition(ModelState.FAILED)
                model.error_code = verdict.reason_code
                self._save(model)
                return model
            model.ready()
            self._save(model)
            self._cancel_events.pop(model_id, None)
            return model

    def cancel(self, model_id: str) -> ManagedModel:
        asset = self.registry.get(model_id)
        model = self._load(asset)
        event = self._cancel_events.get(model_id)
        if event:
            event.set()
        return model

    def verify(self, model_id: str) -> bool:
        asset = self.registry.get(model_id)
        return self.downloader._matches(self.model_root / asset.filename, asset)

    def remove(
        self, model_id: str, *, references: int = 0, runtime: ModelRuntime | None = None
    ) -> None:
        if references:
            raise ModelConflict("managed model is referenced by an active job")
        asset = self.registry.get(model_id)
        with self._lock:
            state = self._load(asset)
            if runtime and state.state == ModelState.READY:
                runtime.remove(state)
            (self.model_root / asset.filename).unlink(missing_ok=True)
            (self.model_root / f".{asset.filename}.part").unlink(missing_ok=True)
            state.state = ModelState.NOT_INSTALLED
            state.downloaded_bytes = 0
            state.operation_id = None
            state.error_code = None
            self._save(state)

    def _load(self, asset: ModelAsset) -> ManagedModel:
        if not self.state_path.is_file():
            return ManagedModel(asset)
        try:
            values = json.loads(self.state_path.read_text(encoding="utf-8"))
            record = values.get(asset.id, {})
            if record.get("version") != asset.version:
                return ManagedModel(asset)
            return ManagedModel(
                asset=asset,
                state=ModelState(record.get("state", ModelState.NOT_INSTALLED.value)),
                downloaded_bytes=int(record.get("downloaded_bytes", 0)),
                operation_id=record.get("operation_id"),
                error_code=record.get("error_code"),
            )
        except (OSError, ValueError, KeyError):
            return ManagedModel(asset)

    def _save(self, model: ManagedModel) -> None:
        values: dict[str, object] = {}
        if self.state_path.is_file():
            try:
                values = json.loads(self.state_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                values = {}
        values[model.asset.id] = {
            "version": model.asset.version,
            "state": model.state.value,
            "downloaded_bytes": model.downloaded_bytes,
            "operation_id": model.operation_id,
            "error_code": model.error_code,
        }
        temp = self.state_path.with_suffix(".tmp")
        temp.write_text(json.dumps(values, indent=2), encoding="utf-8")
        os.replace(temp, self.state_path)

    @staticmethod
    def _progress(
        model: ManagedModel,
        done: int,
        total: int,
        callback: ProgressSink | None,
    ) -> None:
        model.downloaded_bytes = done
        if callback:
            callback(done / total if total else 0.0, "downloading")
