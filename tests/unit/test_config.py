from pathlib import Path

import pytest

from bili_tracker.config.runtime import RuntimeConfig


def test_config_precedence_is_cli_then_env_then_file_then_default(tmp_path: Path):
    config_file = tmp_path / "config.toml"
    config_file.write_text('host = "file-host"\nport = 7000\n', encoding="utf-8")
    config = RuntimeConfig.load(
        cli={"port": 9000},
        environ={"BILI_TRACKER_HOST": "env-host"},
        config_path=config_file,
    )
    assert config.host == "env-host"
    assert config.port == 9000


def test_config_loading_does_not_create_user_directory(tmp_path: Path):
    target = tmp_path / "not-created"
    RuntimeConfig.load(environ={"APPDATA": str(target)})
    assert not target.exists()


def test_non_loopback_bind_requires_explicit_remote_auth():
    config = RuntimeConfig()
    with pytest.raises(ValueError, match="remote.mode_required"):
        config.validate_bind("0.0.0.0")
    remote = RuntimeConfig(remote_mode=True)
    with pytest.raises(ValueError, match="remote.auth_required"):
        remote.validate_bind("0.0.0.0")


def test_concurrent_job_limit_has_safe_default_and_bound():
    assert RuntimeConfig().max_concurrent_jobs == 1
    with pytest.raises(ValueError, match="max_concurrent_jobs"):
        RuntimeConfig.load(environ={"BILI_TRACKER_MAX_CONCURRENT_JOBS": "0"})


def test_user_config_save_is_atomic_and_excludes_unknown_secret_keys(tmp_path: Path):
    home = tmp_path / "config-home"
    RuntimeConfig.save_user_config(
        {"enable_bilibili": True, "deepseek_api_key": "must-not-persist"},
        environ={"APPDATA": str(home)},
    )
    config_path = home / "bili-tracker" / "config.toml"
    assert config_path.is_file()
    assert "deepseek_api_key" not in config_path.read_text(encoding="utf-8")
    loaded = RuntimeConfig.load(environ={"APPDATA": str(home)})
    assert loaded.enable_bilibili is True
