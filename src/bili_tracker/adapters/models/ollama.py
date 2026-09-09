from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlparse

from bili_tracker.adapters.text.ollama import OllamaTextProcessor
from bili_tracker.domain.models import ManagedModel, ModelAsset
from bili_tracker.domain.ports import ModelRuntime, ProgressSink, QualityVerdict


class RuntimeMissing(RuntimeError):
    code = "runtime_missing"


class OllamaRuntime(ModelRuntime):
    id = "ollama"

    def __init__(
        self,
        model_root: Path,
        model_name: str = "bili-tracker-qwen3.5-4b-q6k",
        base_url: str = "http://127.0.0.1:11434",
        executable: str | None = None,
    ) -> None:
        parsed = urlparse(base_url)
        if parsed.hostname not in {"127.0.0.1", "::1", "localhost"}:
            raise ValueError("Ollama runtime must use a loopback URL")
        self.model_root = model_root.expanduser().resolve()
        self.model_name = model_name
        self.base_url = base_url.rstrip("/")
        self.executable = executable or shutil.which("ollama")

    def deploy(self, asset: ModelAsset, progress: ProgressSink) -> None:
        if not self.executable:
            raise RuntimeMissing("Ollama is not installed")
        model_path = (self.model_root / asset.filename).resolve(strict=True)
        modelfile = self.model_root / f"{asset.id}.Modelfile"
        modelfile.write_text(f"FROM {model_path}\n", encoding="utf-8")
        progress(0.0, "registering")
        result = subprocess.run(
            [self.executable, "create", self.model_name, "-f", str(modelfile)],
            capture_output=True,
            text=True,
            check=False,
            timeout=300,
        )
        if result.returncode != 0:
            raise RuntimeError("runtime.deploy_failed")
        progress(1.0, "registered")

    def validate(self, model: ManagedModel) -> QualityVerdict:
        try:
            processor = OllamaTextProcessor(model=self.model_name, base_url=self.base_url)
            output = processor._call("Return the word READY.")
        except RuntimeError as exc:
            return QualityVerdict(False, getattr(exc, "code", "runtime.health_failed"), {})
        return QualityVerdict(bool(output.strip()), "runtime.health_ok", {})

    def remove(self, model: ManagedModel) -> None:
        if not self.executable:
            raise RuntimeMissing("Ollama is not installed")
        result = subprocess.run(
            [self.executable, "rm", model.asset.id],
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
        if result.returncode != 0:
            raise RuntimeError("runtime.remove_failed")
