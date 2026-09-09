from __future__ import annotations

import argparse
import json

from bili_tracker import __version__
from bili_tracker.api.app import create_app
from bili_tracker.config.runtime import RuntimeConfig


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bili-tracker")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("doctor", help="check local runtime configuration")
    serve = sub.add_parser("serve", help="start the local web service")
    serve.add_argument("--host")
    serve.add_argument("--port", type=int)
    args = parser.parse_args(argv)
    config = RuntimeConfig.from_env()
    if args.command == "doctor":
        payload = {
            "status": "ok",
            "data_dir_configured": bool(config.data_dir),
            "loopback_default": config.host in {"127.0.0.1", "::1", "localhost"},
        }
        print(json.dumps(payload, ensure_ascii=False))
        return 0
    if args.command == "serve":
        import uvicorn

        host = args.host or config.host
        port = args.port or config.port
        uvicorn.run(create_app(config), host=host, port=port)
        return 0
    parser.print_help()
    return 0
