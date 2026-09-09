from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path

from bili_tracker.api.app import create_app
from bili_tracker.config.runtime import RuntimeConfig
from bili_tracker.domain.jobs import Job
from bili_tracker.storage.sqlite import SQLiteJobRepository


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="bili-tracker-benchmark-") as directory:
        data_dir = Path(directory)
        repository = SQLiteJobRepository(data_dir / "jobs.sqlite3")
        for _ in range(1000):
            repository.add(Job(source_ref="url:https://www.bilibili.com/video/BV1abCdefGhi"))
        app = create_app(RuntimeConfig(data_dir=data_dir))
        from fastapi.testclient import TestClient

        with TestClient(app) as client:
            samples = []
            for _ in range(20):
                started = time.perf_counter()
                response = client.get("/api/v1/jobs?limit=1000")
                response.raise_for_status()
                samples.append((time.perf_counter() - started) * 1000)
        p95 = sorted(samples)[18]
        print(json.dumps({"samples": len(samples), "p95_ms": round(p95, 2), "target_ms": 300}))
        return 0 if p95 < 300 else 1


if __name__ == "__main__":
    raise SystemExit(main())
