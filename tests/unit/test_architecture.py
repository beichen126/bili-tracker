from pathlib import Path


def test_domain_does_not_import_frameworks_or_vendors():
    root = Path(__file__).parents[2] / "src" / "bili_tracker" / "domain"
    source = "\n".join(path.read_text(encoding="utf-8") for path in root.glob("*.py"))
    forbidden = ("fastapi", "sqlite3", "yt_dlp", "whisper", "ollama", "requests")
    assert not any(f"import {name}" in source or f"from {name}" in source for name in forbidden)
