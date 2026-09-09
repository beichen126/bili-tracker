from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from bili_tracker.domain.errors import InvalidTransition, ManifestError


class ModelState(StrEnum):
    NOT_INSTALLED = "not_installed"
    CHECKING = "checking"
    AWAITING_LICENSE = "awaiting_license"
    DOWNLOADING = "downloading"
    PAUSED = "paused"
    VERIFYING = "verifying"
    DEPLOYING = "deploying"
    VALIDATING = "validating"
    READY = "ready"
    BLOCKED = "blocked"
    FAILED = "failed"


_MODEL_TRANSITIONS: dict[ModelState, frozenset[ModelState]] = {
    ModelState.NOT_INSTALLED: frozenset({ModelState.CHECKING}),
    ModelState.CHECKING: frozenset(
        {ModelState.AWAITING_LICENSE, ModelState.BLOCKED, ModelState.FAILED}
    ),
    ModelState.AWAITING_LICENSE: frozenset({ModelState.DOWNLOADING, ModelState.BLOCKED}),
    ModelState.DOWNLOADING: frozenset({ModelState.PAUSED, ModelState.VERIFYING, ModelState.FAILED}),
    ModelState.PAUSED: frozenset({ModelState.DOWNLOADING, ModelState.BLOCKED}),
    ModelState.VERIFYING: frozenset(
        {ModelState.DOWNLOADING, ModelState.DEPLOYING, ModelState.FAILED}
    ),
    ModelState.DEPLOYING: frozenset({ModelState.VALIDATING, ModelState.FAILED}),
    ModelState.VALIDATING: frozenset({ModelState.READY, ModelState.FAILED}),
    ModelState.READY: frozenset({ModelState.CHECKING, ModelState.NOT_INSTALLED}),
    ModelState.BLOCKED: frozenset({ModelState.CHECKING}),
    ModelState.FAILED: frozenset({ModelState.CHECKING}),
}


@dataclass(frozen=True)
class ModelAsset:
    id: str
    role: str
    version: str
    filename: str
    size_bytes: int
    sha256: str
    license_id: str
    license_url: str
    sources: tuple[str, ...]
    runtime: str
    resource_hints: Mapping[str, str] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, values: Mapping[str, object]) -> ModelAsset:
        required = (
            "id",
            "role",
            "version",
            "filename",
            "size_bytes",
            "sha256",
            "license_id",
            "license_url",
            "sources",
            "runtime",
        )
        missing = [key for key in required if not values.get(key)]
        if missing:
            raise ManifestError(
                "model.manifest_incomplete", f"missing fields: {', '.join(missing)}"
            )
        model_id = str(values["id"])
        sha256 = str(values["sha256"]).lower()
        raw_sources = values["sources"]
        if not isinstance(raw_sources, (list, tuple)):
            raise ManifestError("model.source_invalid", "sources must be a list")
        sources = tuple(str(source) for source in raw_sources if source)
        if not re.fullmatch(r"[a-z0-9][a-z0-9._-]+", model_id):
            raise ManifestError("model.id_invalid", "model id contains unsupported characters")
        if not re.fullmatch(r"[0-9a-f]{64}", sha256):
            raise ManifestError(
                "model.sha256_invalid", "model sha256 must be a 64-character hex digest"
            )
        if int(values["size_bytes"]) <= 0:
            raise ManifestError("model.size_invalid", "model size must be positive")
        if Path(values["filename"]).name != str(values["filename"]):
            raise ManifestError(
                "model.filename_invalid", "model filename must be a plain filename"
            )
        if not str(values["license_url"]).startswith("https://"):
            raise ManifestError("model.license_url_invalid", "license URL must use HTTPS")
        if not sources or any(not source.startswith("https://") for source in sources):
            raise ManifestError("model.source_invalid", "all model sources must use HTTPS")
        return cls(
            id=model_id,
            role=str(values["role"]),
            version=str(values["version"]),
            filename=str(values["filename"]),
            size_bytes=int(values["size_bytes"]),
            sha256=sha256,
            license_id=str(values["license_id"]),
            license_url=str(values["license_url"]),
            sources=sources,
            runtime=str(values["runtime"]),
            resource_hints={
                str(k): str(v) for k, v in dict(values.get("resource_hints", {})).items()
            },
        )


@dataclass
class ManagedModel:
    asset: ModelAsset
    state: ModelState = ModelState.NOT_INSTALLED
    downloaded_bytes: int = 0
    operation_id: str | None = None
    error_code: str | None = None

    def transition(self, target: ModelState) -> None:
        if target not in _MODEL_TRANSITIONS[self.state]:
            raise InvalidTransition("model", self.state.value, target.value)
        self.state = target

    def ready(self) -> None:
        if self.state != ModelState.VALIDATING:
            raise InvalidTransition("model", self.state.value, ModelState.READY.value)
        self.transition(ModelState.READY)
        self.error_code = None
