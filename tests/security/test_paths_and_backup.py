import zipfile
from pathlib import Path

import pytest

from bili_tracker.domain.jobs import ArtifactKind, Job
from bili_tracker.storage.artifacts import LocalArtifactStore
from bili_tracker.storage.backup import BackupError, BackupManager
from bili_tracker.storage.paths import PathContainmentError, resolve_contained
from bili_tracker.storage.sqlite import SQLiteJobRepository


def test_path_containment_rejects_escape(tmp_path: Path):
    root = tmp_path / "root"
    root.mkdir()
    with pytest.raises(PathContainmentError):
        resolve_contained(root, "../outside.txt")


def test_backup_round_trip_and_bad_archive_preserves_current_root(tmp_path: Path):
    data_root = tmp_path / "data"
    repo = SQLiteJobRepository(data_root / "database.sqlite3")
    store = LocalArtifactStore(data_root / "artifacts")
    job = Job(source_ref="local:test.wav")
    job.add_artifact(store.write(job, ArtifactKind.RAW.value, b"raw", "text/plain"))
    repo.add(job)
    manager = BackupManager(data_root, repo)
    backup = manager.create(tmp_path / "backup.zip")
    assert zipfile.is_zipfile(backup)
    (data_root / "marker.txt").write_text("current", encoding="utf-8")
    manager.restore(backup)
    assert not (data_root / "marker.txt").exists()
    assert (data_root / "database.sqlite3").is_file()
    bad = tmp_path / "bad.zip"
    bad.write_bytes(b"not-a-zip")
    with pytest.raises(BackupError):
        manager.restore(bad)
