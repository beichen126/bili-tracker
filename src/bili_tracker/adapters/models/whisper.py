from __future__ import annotations

import importlib
from pathlib import Path

from bili_tracker.domain.models import ManagedModel, ModelAsset
from bili_tracker.domain.ports import ModelRuntime, ProgressSink, QualityVerdict


class WhisperRuntimeMissing(RuntimeError):
    code = "runtime_missing"


class WhisperRuntime(ModelRuntime):
    id = "whisper"

    def __init__(self, model_root: Path, *, loader=None) -> None:
        self.model_root = model_root.expanduser().resolve()
        self.loader = loader

    def deploy(self, asset: ModelAsset, progress: ProgressSink) -> None:
        path = self.model_root / asset.filename
        if not path.name == asset.filename:
            raise RuntimeError("runtime.model_filename_invalid")
        progress(1.0, "registered")

    def validate(self, model: ManagedModel) -> QualityVerdict:
        path = self.model_root / model.asset.filename
        if self.loader:
            try:
                self.loader(path)
            except Exception:
                return QualityVerdict(False, "runtime.health_failed", {})
            return QualityVerdict(True, "runtime.health_ok", {})
        try:
            whisper = importlib.import_module("whisper")
            whisper.load_model(str(path), device="cpu")
        except ImportError:
            return QualityVerdict(False, "runtime_missing", {})
        except Exception:
            return QualityVerdict(False, "runtime.health_failed", {})
        return QualityVerdict(True, "runtime.health_ok", {})

    def remove(self, model: ManagedModel) -> None:
        return None
