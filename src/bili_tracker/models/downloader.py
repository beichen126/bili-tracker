from __future__ import annotations

import hashlib
import os
import shutil
import threading
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from bili_tracker.domain.models import ModelAsset


class DownloadError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class DownloadCancelled(DownloadError):
    def __init__(self) -> None:
        super().__init__(
            "model.download_cancelled", "download cancelled; partial file is resumable"
        )


class DiskSpaceError(DownloadError):
    def __init__(self, required: int, available: int) -> None:
        self.required = required
        self.available = available
        super().__init__("model.disk_space_insufficient", "not enough disk space for model")


@dataclass(frozen=True)
class DownloadResult:
    path: Path
    resumed: bool
    bytes_downloaded: int


Progress = Callable[[int, int], None]


class ResumableDownloader:
    def __init__(self, timeout: float = 30.0, chunk_size: int = 1024 * 1024) -> None:
        self.timeout = timeout
        self.chunk_size = chunk_size

    def download(
        self,
        asset: ModelAsset,
        destination_dir: Path,
        progress: Progress | None = None,
        cancel_event: threading.Event | None = None,
    ) -> DownloadResult:
        destination_dir = destination_dir.expanduser().resolve()
        destination_dir.mkdir(parents=True, exist_ok=True)
        if Path(asset.filename).name != asset.filename:
            raise DownloadError(
                "model.filename_invalid", "manifest filename must be a plain filename"
            )
        available = shutil.disk_usage(destination_dir).free
        if available < asset.size_bytes:
            raise DiskSpaceError(asset.size_bytes, available)
        final = destination_dir / asset.filename
        part = destination_dir / f".{asset.filename}.part"
        if final.is_file() and self._matches(final, asset):
            return DownloadResult(final, False, 0)
        if final.exists():
            final.unlink()
        last_error: DownloadError | None = None
        for source in asset.sources:
            try:
                resumed, count = self._download_one(
                    source, part, asset, progress, cancel_event
                )
                os.replace(part, final)
                return DownloadResult(final, resumed, count)
            except DownloadCancelled:
                raise
            except DownloadError as exc:
                last_error = exc
                part.unlink(missing_ok=True)
        raise last_error or DownloadError("model.download_failed", "all model sources failed")

    def _download_one(
        self,
        source: str,
        part: Path,
        asset: ModelAsset,
        progress: Progress | None,
        cancel_event: threading.Event | None,
    ) -> tuple[bool, int]:
        existing = part.stat().st_size if part.exists() else 0
        request = urllib.request.Request(source)
        if existing:
            request.add_header("Range", f"bytes={existing}-")
        try:
            response = urllib.request.urlopen(request, timeout=self.timeout)
        except OSError as exc:
            raise DownloadError("model.network_error", "model source request failed") from exc
        status = getattr(response, "status", response.getcode())
        resumed = bool(existing and status == 206)
        if existing and not resumed:
            existing = 0
        mode = "ab" if resumed else "wb"
        total = existing
        try:
            with response, part.open(mode) as handle:
                while True:
                    if cancel_event and cancel_event.is_set():
                        raise DownloadCancelled()
                    chunk = response.read(self.chunk_size)
                    if not chunk:
                        break
                    handle.write(chunk)
                    total += len(chunk)
                    if progress:
                        progress(total, asset.size_bytes)
                handle.flush()
                os.fsync(handle.fileno())
        except DownloadCancelled:
            raise
        except OSError as exc:
            raise DownloadError(
                "model.write_error", "model download could not be written"
            ) from exc
        if total != asset.size_bytes:
            raise DownloadError(
                "model.size_mismatch", "downloaded model size does not match manifest"
            )
        if not self._matches(part, asset):
            raise DownloadError(
                "model.hash_mismatch", "downloaded model hash does not match manifest"
            )
        return resumed, total

    @staticmethod
    def _matches(path: Path, asset: ModelAsset) -> bool:
        if not path.is_file() or path.stat().st_size != asset.size_bytes:
            return False
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest() == asset.sha256
