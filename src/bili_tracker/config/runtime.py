from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _default_data_dir() -> Path:
    override = os.environ.get("BILI_TRACKER_DATA_DIR")
    if override:
        return Path(override).expanduser()
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "bili-tracker"


@dataclass(frozen=True)
class RuntimeConfig:
    host: str = "127.0.0.1"
    port: int = 8300
    data_dir: Path = _default_data_dir()
    enable_bilibili: bool = False
    enable_remote_text: bool = False

    @classmethod
    def from_env(cls) -> RuntimeConfig:
        return cls(
            host=os.environ.get("BILI_TRACKER_HOST", cls.host),
            port=int(os.environ.get("BILI_TRACKER_PORT", cls.port)),
            data_dir=Path(
                os.environ.get("BILI_TRACKER_DATA_DIR", str(_default_data_dir()))
            ).expanduser(),
            enable_bilibili=os.environ.get("BILI_TRACKER_ENABLE_BILIBILI", "0") == "1",
            enable_remote_text=os.environ.get("BILI_TRACKER_ENABLE_REMOTE_TEXT", "0") == "1",
        )

    def ensure_data_dir(self) -> Path:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        return self.data_dir
