from fastapi.testclient import TestClient

from bili_tracker.api.app import create_app
from bili_tracker.cli.main import main
from bili_tracker.config.runtime import RuntimeConfig


def test_health_is_minimal(tmp_path):
    client = TestClient(create_app(RuntimeConfig(data_dir=tmp_path)))
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": "0.1.0"}


def test_doctor_does_not_print_absolute_data_path(capsys, tmp_path, monkeypatch):
    monkeypatch.setenv("BILI_TRACKER_DATA_DIR", str(tmp_path / "private-data"))
    assert main(["doctor"]) == 0
    assert str(tmp_path) not in capsys.readouterr().out
