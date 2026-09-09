from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FORBIDDEN = re.compile(
    r"(?:sk-[A-Za-z0-9]{16,}|gh[pousr]_[A-Za-z0-9_\-]{20,}|github_pat_[A-Za-z0-9_\-]{20,}|"
    r"(?:C:|D:|E:)[\\/]Users[\\/]|(?:C:|D:|E:)[\\/](?:软件|任务书|AILab11_news)[\\/])",
    re.IGNORECASE,
)
PRIVATE_NAMES = re.compile(
    r"(?:\.env(?:\.|$)|config\.json$|.*cookies?.*|.*\.sqlite3?$|.*\.(?:pt|gguf|mp4|wav)$)",
    re.I,
)


def tracked_files() -> list[Path]:
    output = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT)
    return [ROOT / item for item in output.decode().split("\0") if item]


def main() -> int:
    files = tracked_files()
    failures: list[str] = []
    for path in files:
        if PRIVATE_NAMES.fullmatch(path.name) or path.stat().st_size > 25_000_000:
            failures.append(f"tracked runtime/private/large file: {path.relative_to(ROOT)}")
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if FORBIDDEN.search(text):
            failures.append(f"possible secret or private path in: {path.relative_to(ROOT)}")
    if failures:
        print("release gate: FAIL")
        print("\n".join(failures))
        return 1
    print(f"release gate: PASS ({len(files)} tracked files scanned)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
