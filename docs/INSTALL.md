# Installation

## Requirements

- Python 3.11 or newer.
- FFmpeg on `PATH` when the selected source needs media extraction.
- Optional: `openai-whisper` for local transcription.
- Optional: Ollama for local Qwen text processing.

The project is tested on Windows and Linux. macOS follows the same Python
installation flow; hardware acceleration and FFmpeg packaging are platform
dependent.

## Clean installation

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
bili-tracker doctor
bili-tracker serve
```

On Linux or macOS, use the equivalent `python3 -m venv`, activation, and
`python -m pip` commands. Open `http://127.0.0.1:8300/`.

## Optional capabilities

Install `.[asr]` for Whisper and `.[sources]` for HTTP/yt-dlp sources. The
application remains usable for configuration and queue management without
either optional group. Configure one or more allowed local input directories
with `BILI_TRACKER_ALLOWED_LOCAL_ROOTS`; no local directory is accepted by
default.

Use `BILI_TRACKER_MAX_CONCURRENT_JOBS` (or `--max-concurrent-jobs` on
`serve`) to change the worker limit. The safe default is one ASR job at a
time, which avoids unexpected GPU contention.

For a remote deployment, set `BILI_TRACKER_REMOTE_MODE=true` and provide a
non-empty `BILI_TRACKER_AUTH_TOKEN`. A non-loopback bind without both settings
is rejected. Keep the service behind an authenticated TLS reverse proxy and
do not expose it directly to the public Internet.

## Offline and proxy use

Model downloads use the configured manifest URLs and resumable `.part` files.
Set standard `HTTP_PROXY`/`HTTPS_PROXY` environment variables if the Python
HTTP stack is configured to use a proxy. An offline install can use a verified
existing model file, but it must still match the manifest size and SHA-256;
the UI must not be marked `ready` from a filename alone.
