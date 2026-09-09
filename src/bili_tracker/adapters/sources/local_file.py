from __future__ import annotations

import mimetypes
from pathlib import Path

from bili_tracker.domain.ports import (
    AcquiredMedia,
    ProgressSink,
    SourceCapabilities,
    SourceInput,
    SourceMetadata,
)
from bili_tracker.storage.paths import resolve_contained


class LocalFileError(ValueError):
    code = "source.local_file_invalid"


class LocalFileSource:
    id = "local-file"
    _types = {
        ".aac": "audio/aac",
        ".flac": "audio/flac",
        ".m4a": "audio/mp4",
        ".mp3": "audio/mpeg",
        ".mp4": "video/mp4",
        ".mkv": "video/x-matroska",
        ".mov": "video/quicktime",
        ".ogg": "audio/ogg",
        ".wav": "audio/wav",
        ".webm": "video/webm",
    }

    def __init__(
        self, allowed_roots: tuple[Path, ...] = (), *, max_bytes: int = 20_000_000_000
    ) -> None:
        self.allowed_roots = tuple(root.expanduser().resolve() for root in allowed_roots)
        self.max_bytes = max_bytes

    def capabilities(self) -> SourceCapabilities:
        return SourceCapabilities(can_probe=True, can_acquire=True)

    def probe(self, source: SourceInput) -> SourceMetadata:
        path = self._validate(source.locator)
        return SourceMetadata(
            canonical_id=str(path),
            title=path.name,
            duration_seconds=None,
            display_locator=path.name,
        )

    def acquire(
        self, source: SourceInput, target_dir: Path, progress: ProgressSink
    ) -> AcquiredMedia:
        path = self._validate(source.locator)
        target_dir = target_dir.expanduser().resolve()
        target_dir.mkdir(parents=True, exist_ok=True)
        target = resolve_contained(target_dir, path.name, allow_missing=True)
        temp = target.with_suffix(target.suffix + ".part")
        total = path.stat().st_size
        copied = 0
        try:
            with path.open("rb") as source_handle, temp.open("wb") as target_handle:
                while chunk := source_handle.read(1024 * 1024):
                    target_handle.write(chunk)
                    copied += len(chunk)
                    progress(copied / total if total else 1.0, "acquiring")
                target_handle.flush()
            temp.replace(target)
        finally:
            temp.unlink(missing_ok=True)
        metadata = self.probe(SourceInput(source.kind, str(path)))
        media_type = self._types.get(path.suffix.lower()) or mimetypes.guess_type(path.name)[0]
        return AcquiredMedia(target, media_type or "application/octet-stream", metadata)

    def _validate(self, locator: str) -> Path:
        candidate = Path(locator).expanduser()
        try:
            resolved = candidate.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise LocalFileError("local file does not exist") from exc
        if not resolved.is_file():
            raise LocalFileError("local input is not a file")
        if not self.allowed_roots:
            raise LocalFileError("no local input directory is configured")
        if not any(self._under(resolved, root) for root in self.allowed_roots):
            raise LocalFileError("local input is outside allowed directories")
        if resolved.suffix.lower() not in self._types:
            guessed, _ = mimetypes.guess_type(resolved.name)
            if not guessed or not (guessed.startswith("audio/") or guessed.startswith("video/")):
                raise LocalFileError("local input type is not supported")
        if resolved.stat().st_size > self.max_bytes:
            raise LocalFileError("local input exceeds configured size limit")
        return resolved

    @staticmethod
    def _under(candidate: Path, root: Path) -> bool:
        try:
            candidate.relative_to(root)
            return True
        except ValueError:
            return False
