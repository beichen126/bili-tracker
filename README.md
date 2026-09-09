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

The first-run path is intentionally short: run `doctor`, open the model
center, accept the applicable model license, install the model, then submit a
local file from an allowed directory. The page shows model progress and the
raw/refined/final artifact boundary. For the complete installation matrix,
model behavior, user workflow and operations checklist, see
[INSTALL](docs/INSTALL.md), [MODELS](docs/MODELS.md),
[USER_GUIDE](docs/USER_GUIDE.md) and [OPERATIONS](docs/OPERATIONS.md).

The interface is a keyboard-accessible single-page workbench with five
surfaces: environment/model center, task submission, task list, task details
through the API, and controlled settings. It has no bundled media, model
weights, cookies or credentials.

## Privacy and safety

- No credentials or cookies are bundled.
- Runtime data is stored outside the source tree by default.
- The public health endpoint exposes process status only.
- URL and local-path inputs are validated before acquisition.
- The project does not bypass DRM, paywalls, CAPTCHAs or access controls.

See [SECURITY.md](SECURITY.md) for reporting and deployment guidance. See [CONTRIBUTING.md](CONTRIBUTING.md) for development checks.

## License

Source code is released under the MIT License. Third-party libraries, model weights and system binaries keep their own licenses; see [NOTICE](NOTICE).
