from __future__ import annotations

import html
import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from urllib.parse import urlencode

from bili_tracker.adapters.sources.http import HttpClientError, SafeHttpClient
from bili_tracker.adapters.sources.url_policy import UrlPolicy, UrlPolicyError
from bili_tracker.adapters.sources.ytdlp import YtDlpSource
from bili_tracker.domain.ports import (
    AcquiredMedia,
    ProgressSink,
    SourceCapabilities,
    SourceInput,
    SourceMetadata,
)


class BilibiliError(RuntimeError):
    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self.code = code


@dataclass(frozen=True)
class BilibiliVideo:
    bvid: str
    title: str
    duration_seconds: float | None
    display_url: str


class BilibiliClient:
    def __init__(
        self,
        *,
        base_url: str = "https://api.bilibili.com",
        http: SafeHttpClient | None = None,
        cookie_provider: Callable[[str], str | None] | None = None,
        cookie_secret_name: str | None = None,
        min_interval: float = 0.2,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.http = http or SafeHttpClient(
            policy=UrlPolicy(allowed_hosts=frozenset({"api.bilibili.com"}), resolve_dns=True)
        )
        self.cookie_provider = cookie_provider
        self.cookie_secret_name = cookie_secret_name
        self.min_interval = max(0.0, min_interval)
        self._last_request = 0.0

    def video(self, identifier: str) -> BilibiliVideo:
        bvid = self._bvid(identifier)
        payload = self._get("/x/web-interface/view", {"bvid": bvid})
        data = self._mapping(payload, "video")
        title = _clean_text(data.get("title"), max_length=300)
        if not title:
            raise BilibiliError("source.schema_invalid", "video title is missing")
        duration = data.get("duration")
        try:
            duration_value = float(duration) if duration is not None else None
        except (TypeError, ValueError):
            duration_value = None
        return BilibiliVideo(bvid, title, duration_value, f"https://www.bilibili.com/video/{bvid}")

    def search(
        self, keyword: str, *, page: int = 1, page_size: int = 20
    ) -> list[dict[str, object]]:
        if not 1 <= page <= 100 or not 1 <= page_size <= 50:
            raise BilibiliError("source.query_invalid", "page bounds exceeded")
        value = _clean_text(keyword, max_length=100)
        if not value:
            raise BilibiliError("source.query_invalid", "keyword is empty")
        payload = self._get(
            "/x/web-interface/search/type",
            {"search_type": "video", "keyword": value, "page": page, "pagesize": page_size},
        )
        data = self._mapping(payload, "search")
        rows = data.get("result", [])
        if not isinstance(rows, list):
            raise BilibiliError("source.schema_invalid", "search result is not a list")
        result = []
        for row in rows[:page_size]:
            if not isinstance(row, Mapping):
                continue
            bvid = row.get("bvid")
            title = _clean_text(row.get("title"), max_length=300)
            if isinstance(bvid, str) and _BVID.fullmatch(bvid) and title:
                result.append({"bvid": bvid, "title": title, "url": f"https://www.bilibili.com/video/{bvid}"})
        return result

    def _get(self, path: str, params: Mapping[str, object]) -> Mapping[str, object]:
        delay = self.min_interval - (time.monotonic() - self._last_request)
        if delay > 0:
            time.sleep(delay)
        query = urlencode({key: str(value) for key, value in params.items()})
        url = f"{self.base_url}{path}?{query}"
        headers = {"User-Agent": "bili-tracker/0.1", "Accept": "application/json"}
        if self.cookie_provider and self.cookie_secret_name:
            cookie = self.cookie_provider(self.cookie_secret_name)
            if cookie:
                headers["Cookie"] = cookie
        self._last_request = time.monotonic()
        try:
            raw = self.http.get_json(url, headers=headers)
        except (HttpClientError, UrlPolicyError) as exc:
            raise BilibiliError(getattr(exc, "code", "source.remote_error")) from exc
        if not isinstance(raw, Mapping):
            raise BilibiliError("source.schema_invalid")
        try:
            code = int(raw.get("code", -1))
        except (TypeError, ValueError) as exc:
            raise BilibiliError("source.schema_invalid") from exc
        if code != 0:
            if code in {-403, -412}:
                raise BilibiliError("source.forbidden")
            if code == -404:
                raise BilibiliError("source.not_found")
            raise BilibiliError("source.platform_error")
        data = raw.get("data")
        if not isinstance(data, Mapping):
            raise BilibiliError("source.schema_invalid")
        return data

    @staticmethod
    def _mapping(value: Mapping[str, object], _context: str) -> Mapping[str, object]:
        return value

    @staticmethod
    def _bvid(identifier: str) -> str:
        match = _BVID.search(identifier)
        if not match:
            raise BilibiliError("source.invalid_identifier")
        return match.group(0)


class BilibiliSource:
    id = "bilibili"

    def __init__(self, client: BilibiliClient, downloader: YtDlpSource | None = None) -> None:
        self.client = client
        self.downloader = downloader or YtDlpSource(allowed_domains=("bilibili.com", "b23.tv"))

    def capabilities(self) -> SourceCapabilities:
        return SourceCapabilities(can_probe=True, can_acquire=True, requires_credentials=False)

    def probe(self, source: SourceInput) -> SourceMetadata:
        video = self.client.video(source.locator)
        return SourceMetadata(video.bvid, video.title, video.duration_seconds, video.display_url)

    def acquire(self, source: SourceInput, target_dir, progress: ProgressSink) -> AcquiredMedia:
        return self.downloader.acquire(SourceInput("url", source.locator), target_dir, progress)


_BVID = re.compile(r"BV[0-9A-Za-z]{10}")


def _clean_text(value: object, *, max_length: int) -> str:
    if not isinstance(value, str):
        return ""
    return html.escape(" ".join(value.split()), quote=True)[:max_length]
