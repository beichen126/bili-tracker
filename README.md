# bili-tracker

`bili-tracker` is a local-first workbench for tracking supported Bilibili sources and turning user-owned or publicly accessible media into searchable text.

The default service listens on `127.0.0.1`. Media, transcripts, credentials and model files stay on the local machine unless the user explicitly enables an external integration. Bilibili discovery and optional text processing are disabled unless configured.

## Quick start

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
bili-tracker doctor
bili-tracker serve
```

Linux/macOS users can replace the virtual-environment activation command with the equivalent command for their shell.

Open `http://127.0.0.1:8300/` after starting the service. FFmpeg is required for media extraction; a local Whisper installation is optional until transcription is requested.

## Privacy and safety

- No credentials or cookies are bundled.
- Runtime data is stored outside the source tree by default.
- The public health endpoint exposes process status only.
- URL and local-path inputs are validated before acquisition.
- The project does not bypass DRM, paywalls, CAPTCHAs or access controls.

See [SECURITY.md](SECURITY.md) for reporting and deployment guidance. See [CONTRIBUTING.md](CONTRIBUTING.md) for development checks.

## License

Source code is released under the MIT License. Third-party libraries, model weights and system binaries keep their own licenses; see [NOTICE](NOTICE).
