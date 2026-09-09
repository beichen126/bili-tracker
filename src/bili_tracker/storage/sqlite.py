from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from uuid import UUID

from bili_tracker.domain.jobs import Artifact, ArtifactKind, Job, JobState


class SQLiteJobRepository:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path.expanduser().resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._migrate()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=30000")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            yield connection
        finally:
            connection.close()

    def _migrate(self) -> None:
        with self._connection() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations "
                "(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
            )
            current = connection.execute("PRAGMA user_version").fetchone()[0]
            if current == 0:
                connection.executescript(
                    """
                    CREATE TABLE jobs (
                        id TEXT PRIMARY KEY,
                        schema_version INTEGER NOT NULL,
                        state TEXT NOT NULL,
                        source_ref TEXT NOT NULL,
                        profile_id TEXT NOT NULL,
                        attempts INTEGER NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        error_code TEXT,
                        degraded INTEGER NOT NULL DEFAULT 0,
                        progress REAL NOT NULL DEFAULT 0
                    );
                    CREATE TABLE artifacts (
                        job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                        kind TEXT NOT NULL,
                        relative_path TEXT NOT NULL,
                        sha256 TEXT NOT NULL,
                        media_type TEXT NOT NULL,
                        derived_from TEXT NOT NULL DEFAULT '[]',
                        PRIMARY KEY (job_id, kind)
                    );
                    CREATE TABLE stage_runs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                        stage TEXT NOT NULL,
                        adapter_id TEXT,
                        started_at TEXT NOT NULL,
                        ended_at TEXT,
                        outcome TEXT,
                        error_code TEXT
                    );
                    PRAGMA user_version=2;
                    INSERT INTO schema_migrations(version, applied_at)
                    VALUES (2, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'));
                    """
                )
            elif current == 1:
                connection.execute(
                    "ALTER TABLE jobs ADD COLUMN progress REAL NOT NULL DEFAULT 0"
                )
                connection.execute("PRAGMA user_version=2")
                connection.execute(
                    "INSERT INTO schema_migrations(version, applied_at) "
                    "VALUES (2, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))"
                )
            elif current != 2:
                raise RuntimeError(f"unsupported database schema version: {current}")

    def add(self, job: Job) -> None:
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "INSERT INTO jobs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                self._job_values(job),
            )
            self._replace_artifacts(connection, job)
            connection.commit()

    def get(self, job_id: str | UUID) -> Job | None:
        with self._connection() as connection:
            row = connection.execute("SELECT * FROM jobs WHERE id=?", (str(job_id),)).fetchone()
            if row is None:
                return None
            return self._load_job(connection, row)

    def list(self, limit: int = 100, offset: int = 0) -> list[Job]:
        if not 1 <= limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")
        if offset < 0:
            raise ValueError("offset must not be negative")
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ? OFFSET ?", (limit, offset)
            ).fetchall()
            return [self._load_job(connection, row) for row in rows]

    def save(self, job: Job) -> None:
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            updated = connection.execute(
                "UPDATE jobs SET schema_version=?, state=?, source_ref=?, profile_id=?, "
                "attempts=?, created_at=?, updated_at=?, error_code=?, degraded=?, progress=? "
                "WHERE id=?",
                (*self._job_values(job)[1:], str(job.id)),
            ).rowcount
            if updated != 1:
                connection.rollback()
                raise KeyError(str(job.id))
            self._replace_artifacts(connection, job)
            connection.commit()

    def delete(self, job_id: str | UUID) -> bool:
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            deleted = connection.execute("DELETE FROM jobs WHERE id=?", (str(job_id),)).rowcount
            connection.commit()
            return deleted == 1

    def claim_next(self) -> Job | None:
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM jobs WHERE state=? ORDER BY created_at LIMIT 1",
                (JobState.QUEUED.value,),
            ).fetchone()
            if row is None:
                connection.rollback()
                return None
            job = self._load_job(connection, row)
            job.begin_attempt()
            connection.execute(
                "UPDATE jobs SET state=?, attempts=?, updated_at=?, error_code=NULL, progress=? "
                "WHERE id=?",
                (
                    job.state.value,
                    job.attempts,
                    job.updated_at.isoformat(),
                    job.progress,
                    str(job.id),
                ),
            )
            connection.commit()
            return job

    def recover_incomplete(self) -> int:
        active = tuple(
            state.value
            for state in (
                JobState.ACQUIRING,
                JobState.TRANSCRIBING,
                JobState.REFINING,
                JobState.REVIEWING,
                JobState.PACKAGING,
            )
        )
        placeholders = ",".join("?" for _ in active)
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            result = connection.execute(
                f"UPDATE jobs SET state='failed', error_code='job.interrupted', "
                f"updated_at=strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE state IN ({placeholders})",
                active,
            )
            connection.commit()
            return result.rowcount

    def artifacts_for(self, job_id: str | UUID) -> list[Artifact]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM artifacts WHERE job_id=? ORDER BY kind", (str(job_id),)
            ).fetchall()
            return [self._artifact_from_row(row) for row in rows]

    def _load_job(self, connection: sqlite3.Connection, row: sqlite3.Row) -> Job:
        artifact_rows = connection.execute(
            "SELECT * FROM artifacts WHERE job_id=?", (row["id"],)
        ).fetchall()
        job = Job(
            id=UUID(row["id"]),
            schema_version=row["schema_version"],
            state=JobState(row["state"]),
            source_ref=row["source_ref"],
            profile_id=row["profile_id"],
            attempts=row["attempts"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            error_code=row["error_code"],
            degraded=bool(row["degraded"]),
            progress=float(row["progress"]),
        )
        for artifact_row in artifact_rows:
            artifact = self._artifact_from_row(artifact_row)
            job.artifacts[artifact.kind] = artifact
        return job

    @staticmethod
    def _job_values(job: Job) -> tuple[object, ...]:
        return (
            str(job.id),
            job.schema_version,
            job.state.value,
            job.source_ref,
            job.profile_id,
            job.attempts,
            job.created_at.isoformat(),
            job.updated_at.isoformat(),
            job.error_code,
            int(job.degraded),
            job.progress,
        )

    @staticmethod
    def _replace_artifacts(connection: sqlite3.Connection, job: Job) -> None:
        connection.execute("DELETE FROM artifacts WHERE job_id=?", (str(job.id),))
        connection.executemany(
            "INSERT INTO artifacts VALUES (?, ?, ?, ?, ?, ?)",
            [
                (
                    str(job.id),
                    artifact.kind.value,
                    artifact.relative_path,
                    artifact.sha256,
                    artifact.media_type,
                    json.dumps(artifact.derived_from),
                )
                for artifact in job.artifacts.values()
            ],
        )

    @staticmethod
    def _artifact_from_row(row: sqlite3.Row) -> Artifact:
        return Artifact(
            kind=ArtifactKind(row["kind"]),
            relative_path=row["relative_path"],
            sha256=row["sha256"],
            media_type=row["media_type"],
            derived_from=tuple(json.loads(row["derived_from"])),
        )
