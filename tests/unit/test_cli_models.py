import json

from bili_tracker.cli.main import main


def test_cli_model_list_and_license_gate_are_machine_readable(capsys, tmp_path, monkeypatch):
    monkeypatch.setenv("BILI_TRACKER_DATA_DIR", str(tmp_path / "private-data"))
    assert main(["models", "list"]) == 0
    listing = json.loads(capsys.readouterr().out)
    assert {item["id"] for item in listing["models"]} == {
        "whisper-large-v3-turbo",
        "qwen3.5-4b-q6k",
    }
    assert str(tmp_path) not in json.dumps(listing)

    assert main(["models", "install", "whisper-large-v3-turbo"]) == 0
    installed = json.loads(capsys.readouterr().out)
    assert installed["state"] == "awaiting_license"
    assert installed["license_accepted_version"] is None
