from pathlib import Path

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
