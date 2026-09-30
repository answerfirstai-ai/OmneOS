"""Command-line entry point for OMNE Core."""

from __future__ import annotations

import argparse
import asyncio
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
from omne.secrets.redact import redact_text


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
        if args.command == "recover":
            return _print_invalid_configuration(exc)
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
    if args.command == "doctor":
        return _run_doctor(settings)
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
    if args.command == "audio":
        return _run_audio(settings)
    if args.command == "input":
        return _run_input(settings)
    if args.command == "storage":
        return _run_storage(settings)
    if args.command == "updates":
        return _run_updates(settings, args)
    if args.command == "recover":
        return _run_recover(settings, args)
    if args.command == "applications":
        return _run_applications(settings)
    if args.command == "browser":
        return _run_browser(settings)
    if args.command == "processes":
        return _run_processes(settings)
    if args.command == "models":
        return _run_models(settings, args)
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
    commands.add_parser("doctor", help="print a system diagnostic without calling NVIDIA")
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
    commands.add_parser("audio", help="print audio diagnostics without opening a microphone")
    commands.add_parser("input", help="print input bindings without reading the keyboard")
    commands.add_parser("storage", help="print storage diagnostics without formatting a disk")
    updates = commands.add_parser("updates", help="print update status without installing packages")
    updates.add_argument(
        "--catalog", default="", help="read a signed catalog instead of installing"
    )
    updates.add_argument(
        "--dry-run",
        action="store_true",
        help="print the apt plan and do not stage or install",
    )
    commands.add_parser("applications", help="print installed applications without launching one")
    commands.add_parser("browser", help="print browser availability without launching one")
    commands.add_parser(
        "processes", help="print the process table without starting or signaling a process"
    )
    recover = commands.add_parser("recover", help="explain startup and run a recovery command")
    recover_commands = recover.add_subparsers(dest="recover_command")
    recover_commands.add_parser("status", help="print the recovery state")
    recover_commands.add_parser("check", help="read health checks without starting services")
    recover_commands.add_parser("safe", help="enter safe mode without erasing user data")
    recover_commands.add_parser("explain", help="print why normal startup failed")
    recover_commands.add_parser("normal", help="leave safe mode when required checks pass")
    recover_commands.add_parser("rollback", help="roll back an update slot without reinstalling")
    mission = commands.add_parser("mission", help="inspect missions")
    mission_commands = mission.add_subparsers(dest="mission_command", required=True)
    mission_commands.add_parser("list", help="list missions")
    show = mission_commands.add_parser("show", help="show one mission")
    show.add_argument("mission_id")
    commands.add_parser("world", help="print the current world state")
    commands.add_parser("agents", help="list agents")
    commands.add_parser("workers", help="list workers")
    models_command = commands.add_parser("models", help="list models and NVIDIA status")
    model_commands = models_command.add_subparsers(dest="models_command")
    model_commands.add_parser("list", help="list models")
    model_test = model_commands.add_parser("test", help="run one provider smoke test")
    model_test.add_argument("provider", choices=["nvidia"])
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


def _run_doctor(settings: Settings) -> int:
    from omne.doctor import diagnose, render

    report = diagnose(
        build_OMNE(settings),
        data_dir=settings.data_dir,
        workspace=settings.workspace_root,
    )
    print(render(report), end="")
    return 0 if report.ready else 1


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


def _run_models(settings: Settings, args: argparse.Namespace) -> int:
    runtime = build_OMNE(settings)
    if getattr(args, "models_command", None) == "test":
        result = asyncio.run(runtime.test_nvidia())
        _print_nvidia_status(result)
        print(json.dumps(result, sort_keys=True, default=str))
        return 0 if result.get("inference") == "PASS" else 1
    status = runtime.nvidia_status()
    _print_nvidia_status(status)
    payload = {"models": runtime.model_views(), "nvidia": status}
    print(json.dumps(payload, sort_keys=True, default=str))
    return 0


def _print_nvidia_status(status: dict[str, object]) -> None:
    print(f"NVIDIA: {status.get('nvidia', 'NOT CONFIGURED')}")
    print(f"Provider: {status.get('provider', 'UNAVAILABLE')}")
    print(f"Model: {status.get('model', '')}")
    print(f"Inference: {status.get('inference', 'NOT RUN')}")
    if status.get("inference") != "NOT RUN":
        print(f"Authentication: {status.get('authentication', 'SKIPPED')}")
    latency = status.get("latency_ms")
    if isinstance(latency, int):
        print(f"Latency: {latency} ms")
    detail = status.get("detail")
    if isinstance(detail, str) and detail and status.get("inference") == "FAIL":
        print(f"Detail: {redact_text(detail)}")


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
        return {"models": runtime.model_views(), "nvidia": runtime.nvidia_status()}
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
    print(json.dumps(build_OMNE(settings).resource_view(), sort_keys=True))
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


def _run_audio(settings: Settings) -> int:
    print(json.dumps(build_OMNE(settings).audio_view(), sort_keys=True))
    return 0


def _run_input(settings: Settings) -> int:
    print(json.dumps(build_OMNE(settings).input_view(), sort_keys=True))
    return 0


def _run_storage(settings: Settings) -> int:
    print(json.dumps(build_OMNE(settings).storage_view(), sort_keys=True))
    return 0


def _run_updates(settings: Settings, args: argparse.Namespace) -> int:
    from omne.updates.select import update_service
    from omne.updates.service import UpdateRejected

    service = update_service(settings.environment, settings.data_dir / "updates")
    catalog = str(args.catalog).strip()
    if not catalog and not args.dry_run:
        print(json.dumps(service.status().model_dump(mode="json"), sort_keys=True))
        return 0
    if not args.dry_run:
        print("error: refusing to install updates on this host", file=sys.stderr)
        return 2
    if not catalog:
        print("error: a catalog is required for a dry-run", file=sys.stderr)
        return 2
    try:
        plan = service.plan(Path(catalog), dry_run=True)
    except UpdateRejected as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(plan.model_dump(mode="json"), sort_keys=True))
    return 0


def _run_applications(settings: Settings) -> int:
    print(json.dumps(build_OMNE(settings).applications_view(), sort_keys=True))
    return 0


def _run_browser(settings: Settings) -> int:
    print(json.dumps(build_OMNE(settings).browser_view(), sort_keys=True))
    return 0


def _run_processes(settings: Settings) -> int:
    print(json.dumps(build_OMNE(settings).processes_view(), sort_keys=True))
    return 0


def _run_recover(settings: Settings, args: argparse.Namespace) -> int:
    from omne.recovery.model import explain_text
    from omne.recovery.select import recovery_service
    from omne.recovery.service import RecoveryRefused

    service = recovery_service(
        settings.environment,
        settings.data_dir / "recovery",
        updates_dir=settings.data_dir / "updates",
        port=settings.port,
    )
    command = str(args.recover_command or "status")
    try:
        status = service.execute(command)
    except RecoveryRefused as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if command == "explain":
        print(explain_text(status))
        return 0
    print(json.dumps(status.model_dump(mode="json"), sort_keys=True))
    return 0


def _print_invalid_configuration(exc: ConfigurationError) -> int:
    from omne.recovery.model import explain_text
    from omne.recovery.service import configuration_status

    status = configuration_status(str(exc))
    print(explain_text(status))
    print(json.dumps(status.model_dump(mode="json"), sort_keys=True))
    return 2


def _run_serve(settings: Settings) -> int:
    from omne.recovery.select import recovery_service

    logger = get_logger("api")
    recovery = recovery_service(
        settings.environment,
        settings.data_dir / "recovery",
        updates_dir=settings.data_dir / "updates",
        port=settings.port,
    )
    recovery.begin_boot()
    try:
        runtime = build_OMNE(settings)
        server = CoreServer(settings, runtime)
        server.start()
    except ValueError as exc:
        recovery.fail_boot(str(exc))
        logger.error("%s", exc)
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except ServerError as exc:
        recovery.fail_boot(str(exc))
        logger.error("%s", exc)
        print(f"error: {exc}", file=sys.stderr)
        return 1
    recovery.mark_ready()

    def _request_stop(signum: int, _frame: FrameType | None) -> None:
        logger.info("shutdown requested signal=%s", signum)
        threading.Thread(target=server.stop, name="OMNE-shutdown", daemon=True).start()

    signal.signal(signal.SIGINT, _request_stop)
    signal.signal(signal.SIGTERM, _request_stop)
    try:
        server.serve_forever()
    finally:
        recovery.mark_stopped()
    logger.info("OMNE Core stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
