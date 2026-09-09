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


def test_repository_supports_bounded_pagination(tmp_path: Path):
    repo = SQLiteJobRepository(tmp_path / "jobs.sqlite3")
    for index in range(3):
        repo.add(Job(source_ref=f"local:{index}"))
    page = repo.list(limit=2, offset=1)
    assert len(page) == 2
    assert page[0].source_ref == "local:1"
