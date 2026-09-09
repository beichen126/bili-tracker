from pathlib import Path

from bili_tracker.domain.jobs import ArtifactKind, Job
from bili_tracker.storage.artifacts import LocalArtifactStore
from bili_tracker.storage.sqlite import SQLiteJobRepository


def test_claim_is_atomic_and_restart_recovery_is_explicit(tmp_path: Path):
    repo = SQLiteJobRepository(tmp_path / "app.sqlite3")
    first = Job(source_ref="local:a.wav")
    second = Job(source_ref="local:b.wav")
    repo.add(first)
    repo.add(second)
    claimed = repo.claim_next()
    assert claimed is not None
    assert claimed.state.value == "acquiring"
    assert repo.claim_next() is not None
    assert repo.claim_next() is None
    assert repo.recover_incomplete() == 2
    assert {job.error_code for job in repo.list()} == {"job.interrupted"}


def test_artifact_write_is_atomic_and_hash_checked(tmp_path: Path):
    store = LocalArtifactStore(tmp_path / "artifacts")
    job = Job(source_ref="local:test.wav")
    artifact = store.write(job, ArtifactKind.RAW.value, b"hello", "text/plain")
    assert store.read(artifact) == b"hello"
    (tmp_path / "artifacts" / artifact.relative_path).write_bytes(b"tampered")
    try:
        store.read(artifact)
    except Exception as exc:
        assert getattr(exc, "code", "") == "artifact.hash_mismatch"
    else:
        raise AssertionError("tampered artifact must be rejected")
