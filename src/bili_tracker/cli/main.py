from __future__ import annotations

import argparse
import importlib.util
import json
import shutil

from bili_tracker import __version__
from bili_tracker.api.app import AppContainer, _load_registry, _model_dto, _runtime, create_app
from bili_tracker.config.runtime import RuntimeConfig


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bili-tracker")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("doctor", help="check local runtime configuration")
    serve = sub.add_parser("serve", help="start the local web service")
    serve.add_argument("--host")
    serve.add_argument("--port", type=int)
    serve.add_argument("--max-concurrent-jobs", type=int)
    models = sub.add_parser("models", help="manage verified local models")
    model_sub = models.add_subparsers(dest="model_command")
    model_sub.add_parser("list", help="list model status")
    for action in ("install", "repair"):
        command = model_sub.add_parser(action, help=f"{action} a model")
        command.add_argument("model_id")
        command.add_argument(
            "--accept-license",
            action="store_true",
            help="confirm the license printed by the model manifest",
        )
    for action in ("cancel", "verify", "remove"):
        command = model_sub.add_parser(action, help=f"{action} a model")
        command.add_argument("model_id")
    args = parser.parse_args(argv)
    config = RuntimeConfig.load(
        cli={
            "host": getattr(args, "host", None),
            "port": getattr(args, "port", None),
            "max_concurrent_jobs": getattr(args, "max_concurrent_jobs", None),
        }
    )
    if args.command == "doctor":
        ffmpeg_ready = shutil.which("ffmpeg") is not None
        whisper_ready = importlib.util.find_spec("whisper") is not None
        ollama_ready = shutil.which("ollama") is not None
        payload = {
            "status": "ok" if ffmpeg_ready else "warning",
            "data_dir_exists": config.data_dir.is_dir(),
            "ffmpeg": "ready" if ffmpeg_ready else "missing",
            "models_registered": len(_load_registry().all()),
            "optional": {
                "whisper_python": "ready" if whisper_ready else "missing",
                "ollama_executable": "ready" if ollama_ready else "missing",
            },
            "loopback_default": config.host in {"127.0.0.1", "::1", "localhost"},
        }
        print(json.dumps(payload, ensure_ascii=False))
        return 0
    if args.command == "serve":
        import uvicorn

        host = config.host
        port = config.port
        try:
            config.validate_bind(host)
        except ValueError as exc:
            parser.error(str(exc))
        uvicorn.run(create_app(config), host=host, port=port)
        return 0
    if args.command == "models":
        services = AppContainer(config)
        if args.model_command == "list":
            print(
                json.dumps(
                    {
                        "models": [
                            _model_dto(services.models, asset.id)
                            for asset in services.registry.all()
                        ]
                    },
                    ensure_ascii=False,
                )
            )
            return 0
        if not args.model_command or not hasattr(args, "model_id"):
            models.print_help()
            return 0
        if args.model_command == "verify":
            print(json.dumps({"verified": services.models.verify(args.model_id)}))
            return 0
        if args.model_command == "cancel":
            model = services.models.cancel(args.model_id)
            print(json.dumps(_model_dto(services.models, model.asset.id)))
            return 0
        if args.model_command == "remove":
            services.models.remove(args.model_id, runtime=_runtime(services, args.model_id))
            print(json.dumps({"removed": args.model_id}))
            return 0
        result = services.models.install(
            args.model_id,
            accept_license=args.accept_license,
            runtime=_runtime(services, args.model_id),
            progress=lambda value, stage: print(
                json.dumps({"stage": stage, "progress": round(value, 4)}), flush=True
            ),
        )
        print(json.dumps(_model_dto(services.models, result.asset.id), ensure_ascii=False))
        return 0
    parser.print_help()
    return 0
