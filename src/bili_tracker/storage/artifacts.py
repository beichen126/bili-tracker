from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path

from bili_tracker.domain.errors import InvariantViolation
from bili_tracker.domain.jobs import Artifact, ArtifactKind, Job
from bili_tracker.storage.paths import resolve_contained

_FILENAMES = {
    ArtifactKind.MANIFEST: "manifest.json",
    ArtifactKind.RAW: "raw.txt",
    ArtifactKind.REFINED: "refined.md",
    ArtifactKind.FINAL: "final.md",
}


class LocalArtifactStore:
    def __init__(self, root: Path) -> None:
        self.root = root.expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def write(
        self,
        job: Job,
        kind: str,
        content: bytes,
        media_type: str,
        derived_from: tuple[str, ...] = (),
    ) -> Artifact:
        artifact_kind = ArtifactKind(kind)
        if artifact_kind in job.artifacts:
            raise InvariantViolation("artifact.duplicate", f"artifact already exists: {kind}")
        job_dir = resolve_contained(self.root, str(job.id), allow_missing=True)
        job_dir.mkdir(parents=True, exist_ok=True)
        filename = _FILENAMES[artifact_kind]
        destination = resolve_contained(job_dir, filename, allow_missing=True)
        if destination.exists():
            raise InvariantViolation(
                "artifact.exists", "refusing to overwrite an existing artifact"
            )
        digest = hashlib.sha256(content).hexdigest()
        fd, temp_name = tempfile.mkstemp(prefix=f".{filename}.", dir=job_dir)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, destination)
        except BaseException:
            Path(temp_name).unlink(missing_ok=True)
            raise
        return Artifact(artifact_kind, f"{job.id}/{filename}", digest, media_type, derived_from)

    def read(self, artifact: Artifact) -> bytes:
        path = resolve_contained(self.root, artifact.relative_path, allow_missing=False)
        content = path.read_bytes()
        if hashlib.sha256(content).hexdigest() != artifact.sha256:
            raise InvariantViolation(
                "artifact.hash_mismatch", "artifact checksum does not match metadata"
            )
        return content

    def delete(self, artifact: Artifact) -> None:
        path = resolve_contained(self.root, artifact.relative_path, allow_missing=False)
        path.unlink()

    def job_dir(self, job_id: str) -> Path:
        return resolve_contained(self.root, job_id, allow_missing=True)
