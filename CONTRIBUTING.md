# Contributing

1. Create a virtual environment with Python 3.11 or newer.
2. Install development dependencies with `python -m pip install -e ".[dev]"`.
3. Run `python -m pytest`, `ruff check .` and `python -m compileall src tests` before submitting a change.
4. Do not commit runtime data, model weights, media, cookies, credentials, private URLs or machine-specific paths.
5. Add a regression test before fixing a reproducible bug.

Keep domain code independent of FastAPI, vendor SDKs and the filesystem. New integrations should implement an adapter port and include contract tests.
