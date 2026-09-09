import pytest

from bili_tracker.domain.errors import InvalidTransition, ManifestError
from bili_tracker.domain.models import ManagedModel, ModelAsset, ModelState


def manifest(**overrides):
    value = {
        "id": "demo-model",
        "role": "text",
        "version": "1",
        "filename": "demo.gguf",
        "size_bytes": 10,
        "sha256": "a" * 64,
        "license_id": "MIT",
        "license_url": "https://example.com/license",
        "sources": ["https://example.com/demo.gguf"],
        "runtime": "demo",
    }
    value.update(overrides)
    return value


def test_manifest_rejects_non_https_or_bad_hash():
    with pytest.raises(ManifestError):
        ModelAsset.from_mapping(manifest(sources=["http://example.com/demo.gguf"]))
    with pytest.raises(ManifestError):
        ModelAsset.from_mapping(manifest(sha256="bad"))


def test_model_ready_requires_validation():
    model = ManagedModel(ModelAsset.from_mapping(manifest()))
    model.transition(ModelState.CHECKING)
    model.transition(ModelState.AWAITING_LICENSE)
    model.transition(ModelState.DOWNLOADING)
    model.transition(ModelState.VERIFYING)
    model.transition(ModelState.DEPLOYING)
    model.transition(ModelState.VALIDATING)
    model.ready()
    assert model.state == ModelState.READY
    with pytest.raises(InvalidTransition):
        model.transition(ModelState.DOWNLOADING)
