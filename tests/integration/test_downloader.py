import hashlib
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from bili_tracker.domain.models import ModelAsset
from bili_tracker.models.downloader import DownloadError, ResumableDownloader


class Handler(BaseHTTPRequestHandler):
    payload = b"0123456789" * 10
    ignore_range = False

    def do_GET(self):  # noqa: N802
        start = 0
        if not self.ignore_range and self.headers.get("Range"):
            start = int(self.headers["Range"].split("=")[1].split("-")[0])
            self.send_response(206)
            self.send_header(
                "Content-Range", f"bytes {start}-{len(self.payload) - 1}/{len(self.payload)}"
            )
        else:
            self.send_response(200)
        self.send_header("Content-Length", str(len(self.payload) - start))
        self.end_headers()
        self.wfile.write(self.payload[start:])

    def log_message(self, *_args):
        return


@pytest.fixture
def server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_port}/model.bin"
    finally:
        httpd.shutdown()
        thread.join()


def asset(source: str, payload: bytes = Handler.payload) -> ModelAsset:
    return ModelAsset(
        id="fixture-model",
        role="test",
        version="1",
        filename="model.bin",
        size_bytes=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
        license_id="MIT",
        license_url="https://example.com/license",
        sources=(source,),
        runtime="fixture",
    )


def test_download_resume_and_verify(server, tmp_path: Path):
    part = tmp_path / ".model.bin.part"
    part.write_bytes(Handler.payload[:17])
    result = ResumableDownloader(chunk_size=3).download(asset(server), tmp_path)
    assert result.resumed is True
    assert result.path.read_bytes() == Handler.payload


def test_server_without_range_does_not_append(server, tmp_path: Path):
    Handler.ignore_range = True
    try:
        (tmp_path / ".model.bin.part").write_bytes(b"bad-prefix")
        result = ResumableDownloader(chunk_size=3).download(asset(server), tmp_path)
        assert result.resumed is False
        assert result.path.read_bytes() == Handler.payload
    finally:
        Handler.ignore_range = False


def test_hash_mismatch_never_installs_final(server, tmp_path: Path):
    wrong = asset(server, b"wrong")
    with pytest.raises(DownloadError) as exc:
        ResumableDownloader().download(wrong, tmp_path)
    assert exc.value.code == "model.size_mismatch"
    assert not (tmp_path / "model.bin").exists()


def test_cancel_keeps_resumable_partial(server, tmp_path: Path):
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(DownloadError) as exc:
        ResumableDownloader().download(asset(server), tmp_path, cancel_event=cancel)
    assert exc.value.code == "model.download_cancelled"
    assert (tmp_path / ".model.bin.part").exists()
