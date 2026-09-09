# User guide

## Local files

Configure an allowed input directory, open the web page, select **本地文件**,
and submit an audio/video file. The path is checked for existence, supported
type, size and resolved symlink/junction containment before it enters the
queue. The API returns only a display filename, not the absolute path.

## Supported URLs

Paste a supported public URL and select **解析并加入队列**. The service probes
metadata first and asks for confirmation before queueing. Bilibili integration
is optional and disabled by default. The project does not collect browser
cookies or bypass access controls; credentials are user-provided through a
controlled secret configuration if a permitted integration needs them.

## Batch and lifecycle

The jobs API accepts up to 100 items and reports `added`, `rejected` and
`duplicate` separately. Jobs can be cancelled while queued, retried after a
failure, or rebuilt after completion. Queue state is persisted in SQLite and
incomplete active work is recovered as an explicit `job.interrupted` failure.

## Results

- `raw` is the first transcription and is never overwritten.
- `refined` is an optional text-processing derivative.
- `final` is the export presented to the user.

If text processing fails under `preserve_raw`, the job remains completed with
`degraded=true` and the raw text remains available. Under `fail_job`, the job
is failed but the raw artifact is still available for download.

## Backups

Create backups from the API settings/operations surface. A backup contains
the SQLite database and verified artifacts; it excludes secrets, model files,
logs, caches and temporary media. Validate before restoring. Restore stages
and validates the archive before replacing the active data directory.
