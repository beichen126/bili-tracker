from __future__ import annotations

import importlib
import threading
from pathlib import Path

from bili_tracker.adapters.sources.url_policy import UrlPolicy, UrlPolicyError
from bili_tracker.domain.ports import (
    AcquiredMedia,
    ProgressSink,
    SourceCapabilities,
    SourceInput,
    SourceMetadata,
)
from bili_tracker.storage.paths import PathContainmentError, resolve_contained


class YtDlpError(RuntimeError):
    code = "source.ytdlp_failed"


class YtDlpCancelled(YtDlpError):
    code = "source.cancelled"


class YtDlpSource:
    id = "yt-dlp"

    def __init__(
        self,
        *,
        allowed_domains: tuple[str, ...] = ("bilibili.com", "b23.tv"),
        loader=None,
        max_bytes: int = 20_000_000_000,
    ) -> None:
        self.allowed_domains = tuple(domain.lower() for domain in allowed_domains)
        self.loader = loader
        self.max_bytes = max_bytes
        self._cancel = threading.Event()

    def capabilities(self) -> SourceCapabilities:
        return SourceCapabilities(can_probe=True, can_acquire=True, requires_credentials=False)

    def cancel(self) -> None:
        self._cancel.set()

    def probe(self, source: SourceInput) -> SourceMetadata:
        url = self._validate_url(source.locator)
        ydl = self._new_ytdl(download=False)
        try:
            info = ydl.extract_info(url, download=False)
        except Exception as exc:
            raise YtDlpError from exc
        return self._metadata(info, url)

    def acquire(
        self, source: SourceInput, target_dir: Path, progress: ProgressSink
    ) -> AcquiredMedia:
        url = self._validate_url(source.locator)
        self._cancel.clear()
        target_dir = target_dir.expanduser().resolve()
        target_dir.mkdir(parents=True, exist_ok=True)
        output_template = str(resolve_contained(target_dir, "%(id)s.%(ext)s", allow_missing=True))
        ydl = self._new_ytdl(download=True, output_template=output_template, progress=progress)
        try:
            info = ydl.extract_info(url, download=True)
        except YtDlpCancelled:
            raise
        except Exception as exc:
            raise YtDlpError from exc
        if not isinstance(info, dict):
            raise YtDlpError("source.schema_invalid")
        downloads = info.get("requested_downloads")
        raw_path = downloads[0].get("filepath") if downloads else None
        path = Path(raw_path) if raw_path else Path(ydl.prepare_filename(info))
        try:
            path = resolve_contained(target_dir, path, allow_missing=False)
        except (PathContainmentError, OSError) as exc:
            raise YtDlpError("source.output_outside_target") from exc
        if path.stat().st_size > self.max_bytes:
            raise YtDlpError("source.media_too_large")
        return AcquiredMedia(path, "video/*", self._metadata(info, url))

    def _new_ytdl(
        self,
        *,
        download: bool,
        output_template: str | None = None,
        progress: ProgressSink | None = None,
    ):
        try:
            module = self.loader() if self.loader else importlib.import_module("yt_dlp")
        except ImportError as exc:
            raise YtDlpError("source.runtime_missing") from exc
        hooks = []
        if progress:
            def hook(status):
                if self._cancel.is_set():
                    raise YtDlpCancelled("download cancelled")
                total = status.get("total_bytes") or status.get("total_bytes_estimate") or 0
                done = status.get("downloaded_bytes", 0)
                progress(done / total if total else 0.0, "acquiring")
            hooks.append(hook)
        options = {
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "noplaylist": True,
            "outtmpl": output_template,
            "progress_hooks": hooks,
            "restrictfilenames": True,
            "socket_timeout": 15,
        }
        if not download:
            options["skip_download"] = True
        return module.YoutubeDL({key: value for key, value in options.items() if value is not None})

    def _validate_url(self, value: str) -> str:
        try:
            parsed = UrlPolicy(
                allowed_hosts=frozenset(self.allowed_domains), resolve_dns=True
            ).validate(value)
        except UrlPolicyError as exc:
            raise YtDlpError("source.url_not_allowed") from exc
        hostname = parsed.hostname.lower().rstrip(".")
        if not any(
            hostname == domain or hostname.endswith("." + domain)
            for domain in self.allowed_domains
        ):
            raise YtDlpError("source.unsupported_domain")
        return value

    @staticmethod
    def _metadata(info: dict, url: str) -> SourceMetadata:
        title = info.get("title")
        title = title[:300] if isinstance(title, str) else None
        duration = info.get("duration")
        duration = float(duration) if isinstance(duration, (int, float)) else None
        identifier = info.get("id")
        return SourceMetadata(str(identifier) if identifier else None, title, duration, url)
