from pathlib import Path


def test_import_has_no_runtime_side_effects(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("BILI_TRACKER_DATA_DIR", str(tmp_path / "data"))
    import bili_tracker

    assert bili_tracker.__version__ == "1.0.0"
    assert not (tmp_path / "data").exists()
