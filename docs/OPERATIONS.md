# Operations

## Data layout

Runtime data lives outside the repository by default. It contains the SQLite
database, artifact files, model state and backups. The public API intentionally
does not expose this absolute path.

## Upgrade and rollback

1. Create and validate a backup.
2. Stop the service and install the new package in the same environment.
3. Start the service and inspect readiness and model status.
4. If rollback is required, stop the service, restore the validated backup and
   install the previous package version.

Database migrations are versioned and fail closed on an unknown schema. Do not
copy model weights, cookies, logs or temporary media into a source checkout.

## Diagnostics

Run `bili-tracker doctor` for a redacted local configuration check. Health is
deliberately minimal. Use the model center error code and the job error code
for support; preserve the raw artifact before attempting a rebuild.

`bili-tracker doctor` reports only redacted readiness flags for FFmpeg, model
manifests and optional Whisper/Ollama runtimes. It never prints the data
directory, credentials or local input roots.

The model lifecycle is also available as machine-readable CLI commands:
`bili-tracker models list`, `install`, `cancel`, `verify`, `repair` and
`remove`. `python scripts/release/benchmark_jobs.py` measures the 1,000-job
list endpoint and fails when the local P95 exceeds 300 ms.

## Security

Keep the default loopback binding for single-user use. Remote mode requires an
explicit token and should be protected by TLS and network policy. Rotate any
credential that may have appeared in a third-party log and report security
issues through the private channel in `SECURITY.md`.
