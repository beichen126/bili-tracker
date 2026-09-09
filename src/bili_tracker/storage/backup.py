from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import uuid
import zipfile
from pathlib import Path

from bili_tracker.storage.paths import PathContainmentError, resolve_contained
from bili_tracker.storage.sqlite import SQLiteJobRepository


class BackupError(ValueError):
    pass


class BackupManager:
    def __init__(self, data_root: Path, repository: SQLiteJobRepository) -> None:
        self.data_root = data_root.expanduser().resolve()
        self.repository = repository
        self.artifacts_root = self.data_root / "artifacts"

    def create(self, destination: Path) -> Path:
        destination = destination.expanduser().resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="bili-tracker-backup-") as temp_dir:
            temp = Path(temp_dir)
            db_copy = temp / "database.sqlite3"
            source = sqlite3.connect(self.repository.db_path)
            target = sqlite3.connect(db_copy)
            try:
                source.backup(target)
            finally:
                source.close()
                target.close()
            records: list[dict[str, object]] = []
            for job in self.repository.list(limit=1000):
                for artifact in job.artifacts.values():
                    source_path = resolve_contained(self.artifacts_root, artifact.relative_path)
                    if not source_path.is_file():
                        raise BackupError("artifact referenced by database is missing")
                    records.append(
                        {
                            "job_id": str(job.id),
                            "relative_path": artifact.relative_path,
                            "sha256": artifact.sha256,
                        }
                    )
            manifest = {
                "format": "bili-tracker-backup",
                "version": 1,
                "files": records,
                "includes": ["database", "artifacts", "manifests-and-text"],
                "excludes": ["secrets", "models", "cache", "logs", "temporary-media"],
            }
            (temp / "backup.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.write(temp / "backup.json", "backup.json")
                archive.write(db_copy, "database.sqlite3")
                for record in records:
                    source_path = resolve_contained(self.artifacts_root, record["relative_path"])
                    archive.write(source_path, f"artifacts/{record['relative_path']}")
        return destination

    def restore(self, archive_path: Path) -> Path:
        archive_path = archive_path.expanduser().resolve(strict=True)
        parent = self.data_root.parent
        staging = parent / f".{self.data_root.name}.restore-{uuid.uuid4().hex}"
        previous = parent / f".{self.data_root.name}.previous-{uuid.uuid4().hex}"
        try:
            self._extract_and_validate(archive_path, staging)
            if self.data_root.exists():
                os.replace(self.data_root, previous)
            os.replace(staging, self.data_root)
            shutil.rmtree(previous, ignore_errors=True)
            return self.data_root
        except BaseException:
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)
            if previous.exists() and not self.data_root.exists():
                os.replace(previous, self.data_root)
            raise

    def _extract_and_validate(self, archive_path: Path, staging: Path) -> None:
        staging.mkdir(parents=True, exist_ok=False)
        try:
            with zipfile.ZipFile(archive_path) as archive:
                names = archive.namelist()
                for name in names:
                    resolve_contained(staging, name, allow_missing=True)
                archive.extractall(staging)
            manifest_path = staging / "backup.json"
            if not manifest_path.is_file():
                raise BackupError("backup manifest is missing")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest.get("format") != "bili-tracker-backup" or manifest.get("version") != 1:
                raise BackupError("unsupported backup format")
            db_path = staging / "database.sqlite3"
            connection = sqlite3.connect(db_path)
            try:
                result = connection.execute("PRAGMA integrity_check").fetchone()[0]
            finally:
                connection.close()
            if result != "ok":
                raise BackupError("backup database failed integrity check")
            artifact_root = staging / "artifacts"
            for record in manifest.get("files", []):
                relative = str(record["relative_path"])
                path = resolve_contained(artifact_root, relative, allow_missing=False)
                if hashlib.sha256(path.read_bytes()).hexdigest() != record["sha256"]:
                    raise BackupError("backup artifact checksum mismatch")
        except (
            KeyError,
            json.JSONDecodeError,
            OSError,
            PathContainmentError,
            zipfile.BadZipFile,
        ) as exc:
            shutil.rmtree(staging, ignore_errors=True)
            raise BackupError("backup validation failed") from exc
