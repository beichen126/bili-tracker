from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def main() -> int:
    output = subprocess.check_output([sys.executable, "-m", "pip", "inspect"], text=True)
    payload = json.loads(output)
    packages = [
        {
            "name": item["metadata"].get("name"),
            "version": item["metadata"].get("version"),
            "license": item["metadata"].get("license"),
        }
        for item in payload.get("installed", [])
        if item.get("metadata", {}).get("name")
    ]
    target = Path("release-artifacts") / "sbom.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps({"format": "pip-inspect", "packages": packages}, indent=2),
        encoding="utf-8",
    )
    print(target)
    return 0


if __name__ == "__main__":
    sys.exit(main())
