import hashlib
from pathlib import Path

from bili_tracker.domain.models import ModelAsset
from bili_tracker.domain.ports import QualityVerdict
from bili_tracker.models.downloader import DownloadResult
from bili_tracker.models.manager import ModelConflict, ModelManager
from bili_tracker.models.registry import ModelRegistry


class FakeRuntime:
    def deploy(self, _asset, _progress):
        return None

    def validate(self, _model):
        return QualityVerdict(True, "ok", {})

    def remove(self, _model):
        return None


class FakeDownloader:
    def __init__(self, payload: bytes):
        self.payload = payload
        self.calls = 0

    def download(self, asset, destination_dir, progress=None, cancel_event=None):
        self.calls += 1
        path = destination_dir / asset.filename
        path.write_bytes(self.payload)
        if progress:
            progress(len(self.payload), len(self.payload))
        return DownloadResult(path, False, len(self.payload))

    @staticmethod
    def _matches(path, asset):
        return path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == asset.sha256


def make_asset(payload=b"fixture-model"):
    return ModelAsset(
        "fixture-model",
        "test",
        "1",
        "model.bin",
        len(payload),
        hashlib.sha256(payload).hexdigest(),
        "MIT",
        "https://example.com/license",
        ("https://example.com/model.bin",),
        "fixture",
    )


def test_manager_requires_license_then_reaches_ready(tmp_path: Path):
    asset = make_asset()
    downloader = FakeDownloader(b"fixture-model")
    manager = ModelManager(
        ModelRegistry({asset.id: asset}), tmp_path / "models", downloader=downloader
    )
    pending = manager.install(asset.id, accept_license=False, runtime=FakeRuntime())
    assert pending.state.value == "awaiting_license"
    ready = manager.install(asset.id, accept_license=True, runtime=FakeRuntime())
    assert ready.state.value == "ready"
    restored = manager._load(asset)
    assert restored.license_accepted_version == asset.version
    assert restored.license_accepted_at
    manager.install(asset.id, accept_license=True, runtime=FakeRuntime())
    assert downloader.calls == 1


def test_manager_remove_conflict_is_explicit(tmp_path: Path):
    asset = make_asset(b"x")
    manager = ModelManager(ModelRegistry({asset.id: asset}), tmp_path / "models")
    try:
        manager.remove(asset.id, references=1)
    except ModelConflict as exc:
        assert exc.code == "model.in_use"
    else:
        raise AssertionError("active model references must block removal")
