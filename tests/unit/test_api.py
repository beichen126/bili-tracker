from fastapi.testclient import TestClient

from bili_tracker.api.app import create_app
from bili_tracker.cli.main import main
from bili_tracker.config.runtime import RuntimeConfig


def test_health_is_minimal(tmp_path):
    client = TestClient(create_app(RuntimeConfig(data_dir=tmp_path)))
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": "1.0.0"}


def test_doctor_does_not_print_absolute_data_path(capsys, tmp_path, monkeypatch):
    monkeypatch.setenv("BILI_TRACKER_DATA_DIR", str(tmp_path / "private-data"))
    assert main(["doctor"]) == 0
    assert str(tmp_path) not in capsys.readouterr().out


def test_api_models_settings_jobs_and_static_ui_are_public_contract(tmp_path):
    media = tmp_path / "lesson.wav"
    media.write_bytes(b"RIFF")
    config = RuntimeConfig(data_dir=tmp_path / "data", allowed_local_roots=(tmp_path,))
    client = TestClient(create_app(config))

    models = client.get("/api/v1/models")
    assert models.status_code == 200
    assert {model["id"] for model in models.json()["models"]} == {
        "whisper-large-v3-turbo",
        "qwen3.5-4b-q6k",
    }
    settings = client.patch(
        "/api/v1/settings",
        json={"bilibili_cookie": "do-not-return-this", "deepseek_api_key": "secret"},
    )
    assert settings.status_code == 200
    assert "do-not-return-this" not in settings.text
    assert "secret" not in settings.text
    assert settings.json()["settings"]["bilibili_cookie_configured"] is True

    probe = client.post("/api/v1/sources/probe", json={"kind": "local", "locator": str(media)})
    assert probe.status_code == 200
    assert probe.json()["source"]["canonical_id"] is None
    assert probe.json()["source"]["display_locator"] == "lesson.wav"
    assert str(tmp_path) not in probe.text
    jobs = client.post(
        "/api/v1/jobs",
        json={"items": [{"source": {"kind": "local", "locator": str(media)}}]},
    )
    assert jobs.status_code == 201
    assert len(jobs.json()["added"]) == 1
    duplicate = client.post(
        "/api/v1/jobs",
        json={"items": [{"source": {"kind": "local", "locator": str(media)}}]},
    )
    assert len(duplicate.json()["duplicate"]) == 1
    assert client.get("/").status_code == 200


def test_packaged_manifest_directory_is_used_when_source_root_is_absent(monkeypatch):
    from bili_tracker.api import app as api_module

    registry = api_module._load_registry()
    assert len(registry.all()) == 2


def test_model_license_gate_is_idempotent(tmp_path):
    client = TestClient(create_app(RuntimeConfig(data_dir=tmp_path)))
    first = client.post(
        "/api/v1/models/whisper-large-v3-turbo/install", json={"accept_license": False}
    )
    second = client.post(
        "/api/v1/models/whisper-large-v3-turbo/install", json={"accept_license": False}
    )
    assert first.status_code == second.status_code == 202
    assert first.json()["model"]["state"] == "awaiting_license"
    assert second.json()["model"]["state"] == "awaiting_license"


def test_api_error_has_stable_shape_and_no_exception_details(tmp_path):
    client = TestClient(create_app(RuntimeConfig(data_dir=tmp_path)))
    response = client.get("/api/v1/jobs/not-a-job")
    assert response.status_code == 404
    payload = response.json()["error"]
    assert set(payload) == {"code", "message", "request_id", "retryable", "details"}
    assert "Traceback" not in response.text


def test_remote_mode_requires_bearer_token_and_does_not_echo_it(tmp_path):
    from bili_tracker.config.secrets import SecretValue

    config = RuntimeConfig(
        data_dir=tmp_path,
        remote_mode=True,
        auth_token=SecretValue("keep-this-private"),
    )
    client = TestClient(create_app(config))
    assert client.get("/api/v1/health").status_code == 401
    response = client.get(
        "/api/v1/health", headers={"Authorization": "Bearer keep-this-private"}
    )
    assert response.status_code == 200
    assert "keep-this-private" not in response.text
    capabilities = client.get(
        "/api/v1/capabilities", headers={"Authorization": "Bearer keep-this-private"}
    )
    assert {item["id"] for item in capabilities.json()["sources"]} == {"url"}
