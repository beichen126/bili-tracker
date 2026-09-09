from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse

import pytest

from bili_tracker.adapters.sources.bilibili import BilibiliClient, BilibiliError, BilibiliSource
from bili_tracker.adapters.sources.http import HttpResponse, SafeHttpClient
from bili_tracker.adapters.sources.local_file import LocalFileError, LocalFileSource
from bili_tracker.adapters.sources.url_policy import UrlPolicy, UrlPolicyError
from bili_tracker.domain.ports import SourceInput


def test_local_file_rejects_escape_and_accepts_supported_type(tmp_path: Path):
    root = tmp_path / "allowed"
    root.mkdir()
    media = root / "音频 file.wav"
    media.write_bytes(b"audio")
    source = LocalFileSource((root,))
    assert source.probe(SourceInput("local", str(media))).title == media.name
    with pytest.raises(LocalFileError):
        source.probe(SourceInput("local", str(tmp_path / "outside.wav")))


def test_local_file_symlink_is_checked_after_resolution(tmp_path: Path):
    root = tmp_path / "allowed"
    root.mkdir()
    outside = tmp_path / "outside.wav"
    outside.write_bytes(b"audio")
    link = root / "link.wav"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation unavailable")
    with pytest.raises(LocalFileError):
        LocalFileSource((root,)).probe(SourceInput("local", str(link)))


def test_url_policy_rejects_local_and_non_http_urls():
    policy = UrlPolicy()
    for value in ("file:///etc/passwd", "http://127.0.0.1/a", "http://localhost/a"):
        with pytest.raises(UrlPolicyError):
            policy.validate(value)


def test_bilibili_client_schema_and_metadata_are_bounded():
    def transport(method, url, headers, timeout, max_bytes):
        assert method == "GET"
        assert "Cookie" not in headers
        return HttpResponse(
            200,
            {},
            json.dumps({"code": 0, "data": {"title": "<title>", "duration": 12}}).encode(),
        )

    http = SafeHttpClient(
        policy=UrlPolicy(allowed_hosts=frozenset({"api.bilibili.com"})),
        transport=transport,
    )
    video = BilibiliClient(http=http, min_interval=0).video(
        "https://www.bilibili.com/video/BV1abCdefGhi"
    )
    assert video.bvid == "BV1abCdefGhi"
    assert "&lt;title&gt;" in video.title


def test_bilibili_client_maps_platform_error():
    def transport(method, url, headers, timeout, max_bytes):
        return HttpResponse(200, {}, b'{"code": -404, "data": null}')

    client = BilibiliClient(
        http=SafeHttpClient(
            policy=UrlPolicy(allowed_hosts=frozenset({"api.bilibili.com"})), transport=transport
        ),
        min_interval=0,
    )
    with pytest.raises(BilibiliError) as error:
        client.video("BV1abCdefGhi")
    assert error.value.code == "source.not_found"


def test_bilibili_client_exposes_bounded_public_feeds():
    row = {"bvid": "BV1abCdefGhi", "title": "<video>", "length": "01:02", "play": 42}

    def transport(method, url, headers, timeout, max_bytes):
        assert method == "GET"
        payloads = {
            "/x/space/wbi/arc/search": {"code": 0, "data": {"list": {"vlist": [row]}}},
            "/x/web-interface/popular": {"code": 0, "data": {"list": [row]}},
            "/x/web-interface/ranking/v2": {"code": 0, "data": {"list": [row]}},
            "/x/web-interface/index/top/rcmd": {"code": 0, "data": {"item": [row]}},
        }
        return HttpResponse(
            200, {}, json.dumps(payloads[urlparse(url).path]).encode("utf-8")
        )

    client = BilibiliClient(
        http=SafeHttpClient(
            policy=UrlPolicy(allowed_hosts=frozenset({"api.bilibili.com"})), transport=transport
        ),
        min_interval=0,
    )
    assert "space" in BilibiliSource(client).capabilities().operations
    for values in (
        client.space(123, page_size=1),
        client.hot(page_size=1),
        client.ranking(page_size=1),
        client.recommendation(page_size=1),
    ):
        assert len(values) == 1
        assert values[0]["bvid"] == row["bvid"]
        assert values[0]["duration_seconds"] == 62.0
        assert values[0]["views"] == 42

    with pytest.raises(BilibiliError) as error:
        client.space(123, page_size=51)
    assert error.value.code == "source.query_invalid"


def test_http_client_rejects_oversized_response():
    http = SafeHttpClient(
        policy=UrlPolicy(allowed_hosts=frozenset({"example.com"})),
        max_response_bytes=4,
        transport=lambda *args: HttpResponse(200, {}, b"12345"),
    )
    with pytest.raises(Exception) as error:
        http.get_json("https://example.com/api")
    assert getattr(error.value, "code", "") == "source.response_too_large"
