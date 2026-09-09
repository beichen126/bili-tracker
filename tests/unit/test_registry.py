from pathlib import Path

from bili_tracker.models.registry import ModelRegistry


def test_public_manifests_are_complete_and_allowlisted():
    registry = ModelRegistry.from_directory(Path(__file__).parents[2] / "model-manifests")
    assert {asset.id for asset in registry.all()} == {
        "whisper-large-v3-turbo",
        "qwen3.5-4b-q6k",
    }
    assert all(asset.size_bytes > 0 and len(asset.sha256) == 64 for asset in registry.all())
