# Model center

The repository contains manifests, not weights. The model center exposes the
license, source, size, checksum, runtime and current lifecycle state before an
installation starts.

| Model | Role | Runtime | Size in manifest | License |
|---|---|---|---:|---|
| `whisper-large-v3-turbo` | transcription | local Whisper | 1.51 GiB | MIT |
| `qwen3.5-4b-q6k` | text processing | Ollama | 3.42 GiB | Apache-2.0 |

Accept the displayed license once, then choose Install. A stopped download
keeps its partial file and can be resumed. Verification requires both exact
file size and SHA-256. A failed verification never becomes `installed` or
`ready`.

Whisper validation loads the model and requires a usable local Whisper runtime.
Qwen validation requires Ollama, creates the managed Modelfile with an
argument-array subprocess call, and performs a local health prompt. The
application does not install system software with elevation.

Repair repeats the safe check/download/deploy path. Removing a model deletes
only the managed model asset and resets its local state; active references are
refused. Model manifests are reviewed for source, checksum, license and a
controlled smoke test before release.
