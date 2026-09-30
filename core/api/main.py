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
from core.memory.retrieval import MemoryAccessError
from core.orchestrator.service import OMNE
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
        return _run_execute(settings, args.objective, dry_run=bool(args.dry_run))
    if args.command == "compute":
        return _run_compute(settings)
    if args.command == "display":
        return _run_display(settings)
    if args.command == "windowing":
        return _run_windowing(settings)
    if args.command == "hardware":
        return _run_hardware(settings)
    if args.command == "network":
        return _run_network(settings)
    return _run_inspection(settings, args)


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
    execute.add_argument(
        "--dry-run",
        action="store_true",
        help="show the plan without running tools",
    )
    commands.add_parser("compute", help="print one host resource snapshot")
    commands.add_parser("display", help="print display diagnostics without starting a session")
    commands.add_parser("windowing", help="print window state without commanding the compositor")
    commands.add_parser(
        "hardware", help="print hardware discovered from Linux without changing drivers"
    )
    commands.add_parser("network", help="print network state without changing the host stack")
    mission = commands.add_parser("mission", help="inspect missions")
    mission_commands = mission.add_subparsers(dest="mission_command", required=True)
    mission_commands.add_parser("list", help="list missions")
    show = mission_commands.add_parser("show", help="show one mission")
    show.add_argument("mission_id")
    commands.add_parser("world", help="print the current world state")
    commands.add_parser("agents", help="list agents")
    commands.add_parser("workers", help="list workers")
    commands.add_parser("models", help="list models")
    commands.add_parser("capabilities", help="list capabilities")
    trace = commands.add_parser("trace", help="show one trace")
    trace.add_argument("trace_id")
    commands.add_parser("events", help="list recent events")
    memory = commands.add_parser("memory", help="list one memory scope")
    memory.add_argument("--scope", required=True)
    memory.add_argument("--scope-key", required=True)
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


def _run_execute(settings: Settings, objective: str, *, dry_run: bool) -> int:
    try:
        task = build_OMNE(settings).execute_sync(objective, dry_run=dry_run)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"id": task.id, "status": task.status.value}, sort_keys=True))
    if task.status is TaskStatus.COMPLETED:
        return 0
    if task.status is TaskStatus.WAITING:
        return 3
    return 1


def _run_inspection(settings: Settings, args: argparse.Namespace) -> int:
    try:
        runtime = build_OMNE(settings)
        payload = _inspection_payload(runtime, args)
    except (KeyError, ValueError, MemoryAccessError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(payload, sort_keys=True, default=str))
    return 0


def _inspection_payload(runtime: OMNE, args: argparse.Namespace) -> object:
    if args.command == "mission" and args.mission_command == "list":
        return {
            "missions": [mission.model_dump(mode="json") for mission in runtime.list_missions()]
        }
    if args.command == "mission" and args.mission_command == "show":
        return {"mission": runtime.get_mission(args.mission_id).model_dump(mode="json")}
    if args.command == "world":
        return {"world": runtime.world_view()}
    if args.command == "agents":
        return {"agents": runtime.agent_views()}
    if args.command == "workers":
        return {"workers": runtime.worker_views()}
    if args.command == "models":
        return {"models": runtime.model_views()}
    if args.command == "capabilities":
        return {"capabilities": runtime.capability_views()}
    if args.command == "trace":
        return runtime.trace_view(args.trace_id)
    if args.command == "events":
        return {
            "events": [event.model_dump(mode="json") for event in runtime.list_events(limit=50)]
        }
    if args.command == "memory":
        return {
            "records": runtime.list_memory(scope=args.scope, scope_key=args.scope_key, limit=20)
        }
    raise ValueError(f"unknown command {args.command}")


def _run_compute(settings: Settings) -> int:
    snapshot = build_OMNE(settings).compute_status()
    print(json.dumps(snapshot.model_dump(), sort_keys=True))
    return 0


def _run_display(settings: Settings) -> int:
    print(json.dumps(build_OMNE(settings).display_view(), sort_keys=True))
    return 0


def _run_windowing(settings: Settings) -> int:
    print(json.dumps(build_OMNE(settings).windowing_view(), sort_keys=True))
    return 0


def _run_hardware(settings: Settings) -> int:
    print(json.dumps(build_OMNE(settings).hardware_view(), sort_keys=True))
    return 0


def _run_network(settings: Settings) -> int:
    print(json.dumps(build_OMNE(settings).network_view(), sort_keys=True))
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
