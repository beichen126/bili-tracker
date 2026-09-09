from __future__ import annotations

import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from bili_tracker.config.secrets import SecretValue


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
    data_dir: Path = field(default_factory=_default_data_dir)
    allowed_local_roots: tuple[Path, ...] = ()
    enable_bilibili: bool = False
    enable_remote_text: bool = False
    remote_mode: bool = False
    auth_token: SecretValue | None = None
    log_level: str = "INFO"

    @staticmethod
    def user_config_path(environ: Mapping[str, str] | None = None) -> Path:
        env = environ if environ is not None else os.environ
        if os.name == "nt":
            base = Path(env.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        else:
            base = Path(env.get("XDG_CONFIG_HOME", Path.home() / ".config"))
        return base / "bili-tracker" / "config.toml"

    @classmethod
    def load(
        cls,
        cli: Mapping[str, object] | None = None,
        environ: Mapping[str, str] | None = None,
        config_path: Path | None = None,
    ) -> RuntimeConfig:
        env = environ or os.environ
        values: dict[str, object] = {}
        path = config_path or cls.user_config_path(env)
        if path.is_file():
            with path.open("rb") as handle:
                values.update(tomllib.load(handle))
        env_values: dict[str, object] = {}
        mapping = {
            "host": "BILI_TRACKER_HOST",
            "port": "BILI_TRACKER_PORT",
            "data_dir": "BILI_TRACKER_DATA_DIR",
            "log_level": "BILI_TRACKER_LOG_LEVEL",
        }
        for key, env_key in mapping.items():
            if env_key in env and env[env_key] != "":
                env_values[key] = env[env_key]
        bool_mapping = {
            "enable_bilibili": "BILI_TRACKER_ENABLE_BILIBILI",
            "enable_remote_text": "BILI_TRACKER_ENABLE_REMOTE_TEXT",
            "remote_mode": "BILI_TRACKER_REMOTE_MODE",
        }
        for key, env_key in bool_mapping.items():
            if env_key in env:
                env_values[key] = env[env_key] in {"1", "true", "True", "yes"}
        if "BILI_TRACKER_ALLOWED_LOCAL_ROOTS" in env:
            env_values["allowed_local_roots"] = env["BILI_TRACKER_ALLOWED_LOCAL_ROOTS"].split(
                os.pathsep
            )
        values.update(env_values)
        values.update({key: value for key, value in (cli or {}).items() if value is not None})
        roots = values.get("allowed_local_roots", ())
        if isinstance(roots, str):
            roots = [roots]
        return cls(
            host=str(values.get("host", cls.host)),
            port=int(values.get("port", cls.port)),
            data_dir=Path(values.get("data_dir") or _default_data_dir()).expanduser(),
            allowed_local_roots=tuple(Path(root).expanduser() for root in roots if root),
            enable_bilibili=bool(values.get("enable_bilibili", cls.enable_bilibili)),
            enable_remote_text=bool(values.get("enable_remote_text", cls.enable_remote_text)),
            remote_mode=bool(values.get("remote_mode", cls.remote_mode)),
            auth_token=(
                SecretValue(env["BILI_TRACKER_AUTH_TOKEN"])
                if env.get("BILI_TRACKER_AUTH_TOKEN")
                else None
            ),
            log_level=str(values.get("log_level", cls.log_level)).upper(),
        )

    @classmethod
    def from_env(cls) -> RuntimeConfig:
        return cls.load()

    def ensure_data_dir(self) -> Path:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        return self.data_dir

    def validate_bind(self, host: str | None = None) -> None:
        bound_host = host or self.host
        if bound_host not in {"127.0.0.1", "::1", "localhost"}:
            if not self.remote_mode:
                raise ValueError("remote.mode_required")
            if not self.auth_token or not self.auth_token.is_set:
                raise ValueError("remote.auth_required")
