"""Command-line entry point for OMNE Core."""

from __future__ import annotations

import argparse
import json
import signal
import sys
import threading
from pathlib import Path
from types import FrameType

from core import __version__
from core.api.runtime import build_OMNE
from core.api.server import CoreServer, ServerError
from core.config.errors import ConfigurationError
from core.config.settings import (
    Settings,
    load_settings,
    override_settings,
    prepare_runtime_directories,
)
from core.logging_config import configure_logging, get_logger
from core.orchestrator.task import TaskStatus


def main(argv: list[str] | None = None) -> int:
    """Run the OMNE command and return a process status code."""

    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.version:
        print(__version__)
        return 0
    if args.command is None:
        parser.print_help()
        return 0

    try:
        settings = load_settings(config_path=args.config)
        if args.command == "serve":
            settings = _with_bind_overrides(
                settings,
                host=getattr(args, "host", None),
                port=getattr(args, "port", None),
            )
    except ConfigurationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    configure_logging(settings)
    try:
        prepare_runtime_directories(settings)
    except ConfigurationError as exc:
        get_logger("core").error("%s", exc)
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.command == "check":
        return _run_check(settings)
    if args.command == "serve":
        return _run_serve(settings)
    if args.command == "execute":
        return _run_execute(settings, args.objective)
    if args.command == "compute":
        return _run_compute(settings)
    print(f"error: unknown command {args.command}", file=sys.stderr)
    return 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="OMNE",
        description="OMNE Core commands.",
    )
    parser.add_argument("--version", action="store_true", help="print the core version and exit")
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="path to a TOML settings file",
    )
    commands = parser.add_subparsers(dest="command")
    commands.add_parser("check", help="load configuration, prepare directories, and exit")
    serve = commands.add_parser("serve", help="serve the local core HTTP API")
    serve.add_argument("--host", default=None, help="override the configured bind host")
    serve.add_argument("--port", type=int, default=None, help="override the configured bind port")
    execute = commands.add_parser("execute", help="plan and run one objective")
    execute.add_argument("objective", help="objective text")
    commands.add_parser("compute", help="print one host resource snapshot")
    return parser


def _with_bind_overrides(settings: Settings, *, host: str | None, port: int | None) -> Settings:
    updates: dict[str, object] = {}
    if host is not None:
        updates["host"] = host
    if port is not None:
        updates["port"] = port
    return override_settings(settings, updates)


def _run_check(settings: Settings) -> int:
    logger = get_logger("core")
    logger.debug(
        "workspace_root=%s data_dir=%s",
        settings.workspace_root,
        settings.data_dir,
    )
    logger.info(
        "OMNE Core check passed version=%s environment=%s",
        __version__,
        settings.environment,
    )
    print(f"OMNE-core {__version__} {settings.environment} ok")
    return 0


def _run_execute(settings: Settings, objective: str) -> int:
    try:
        task = build_OMNE(settings).execute_sync(objective)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"id": task.id, "status": task.status.value}, sort_keys=True))
    if task.status is TaskStatus.COMPLETED:
        return 0
    if task.status is TaskStatus.WAITING:
        return 3
    return 1


def _run_compute(settings: Settings) -> int:
    snapshot = build_OMNE(settings).compute_status()
    print(json.dumps(snapshot.model_dump(), sort_keys=True))
    return 0


def _run_serve(settings: Settings) -> int:
    logger = get_logger("api")
    try:
        runtime = build_OMNE(settings)
    except ValueError as exc:
        logger.error("%s", exc)
        print(f"error: {exc}", file=sys.stderr)
        return 2
    server = CoreServer(settings, runtime)

    def _request_stop(signum: int, _frame: FrameType | None) -> None:
        logger.info("shutdown requested signal=%s", signum)
        threading.Thread(target=server.stop, name="OMNE-shutdown", daemon=True).start()

    signal.signal(signal.SIGINT, _request_stop)
    signal.signal(signal.SIGTERM, _request_stop)
    try:
        server.serve_forever()
    except ServerError as exc:
        logger.error("%s", exc)
        print(f"error: {exc}", file=sys.stderr)
        return 1
    logger.info("OMNE Core stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
