"""Gateway actions for observer modules.

These tools call the existing services. They do not format disks, open a
microphone, grab the keyboard, or send a shell command.
"""

from __future__ import annotations

from typing import Any, Literal

from core.tools.base import ToolContext, ToolError
from omne.audio.model import AudioRequest
from omne.audio.service import AudioService
from omne.display.provider import DisplayProvider
from omne.hardware.service import HardwareService
from omne.input.model import InputRequest
from omne.input.service import InputService
from omne.network.model import NetworkRequest
from omne.network.service import NetworkService
from omne.storage.service import StorageService

_UNSAFE = set("|&;<>`$()")
_REJECTED = {"argv", "command", "shell", "exec", "cmd", "secret", "password"}


class _ObserverTool:
    def __init__(self, tool_id: str, environment: str) -> None:
        self.id = tool_id
        self._environment = environment

    def _agent(self, context: ToolContext) -> str:
        return context.agent_id or "local"

    def _empty(self, arguments: dict[str, Any]) -> dict[str, Any]:
        _reject_command(arguments)
        if arguments:
            raise ToolError(f"{self.id} takes no arguments", code="invalid_input")
        return {}


def _reject_command(arguments: dict[str, Any]) -> None:
    if any(key in arguments for key in _REJECTED):
        raise ToolError("observer action does not accept a shell command", code="invalid_input")


def _text(arguments: dict[str, Any], key: str) -> str:
    _reject_command(arguments)
    value = arguments.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ToolError(f"{key} must be a non-empty string", code="invalid_input")
    text = " ".join(value.split())
    if any(character in text for character in _UNSAFE):
        raise ToolError(f"{key} is not a command", code="invalid_input")
    return text


class NetworkScanTool(_ObserverTool):
    def __init__(self, service: NetworkService, environment: str) -> None:
        super().__init__("network.scan", environment)
        self._service = service

    def validate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return self._empty(arguments)

    def execute(self, arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        return _applied(
            self._service.apply(
                NetworkRequest(action="scan", agent_id=self._agent(context)),
                {},
                self._environment,
                permitted=True,
            )
        )


class NetworkChangeTool(_ObserverTool):
    def __init__(self, tool_id: str, service: NetworkService, environment: str) -> None:
        super().__init__(tool_id, environment)
        self._service = service

    def validate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        interface = _text(arguments, "interface")
        cleaned: dict[str, Any] = {"interface": interface}
        if "ssid" in arguments:
            cleaned["ssid"] = _text(arguments, "ssid")
        extra = set(arguments) - {"interface", "ssid"}
        if extra:
            raise ToolError("network change has an unknown argument", code="invalid_input")
        return cleaned

    def execute(self, arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        action = _network_action(self.id)
        ssid = arguments.get("ssid")
        return _applied(
            self._service.apply(
                NetworkRequest(
                    action=action,
                    agent_id=self._agent(context),
                    interface=str(arguments["interface"]),
                    ssid=ssid if isinstance(ssid, str) else None,
                ),
                {},
                self._environment,
                permitted=True,
            )
        )


class AudioChangeTool(_ObserverTool):
    def __init__(self, tool_id: str, service: AudioService, environment: str) -> None:
        super().__init__(tool_id, environment)
        self._service = service

    def validate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        device = _text(arguments, "device")
        if self.id == "audio.set_volume":
            volume = arguments.get("volume")
            if isinstance(volume, bool) or not isinstance(volume, int) or not 0 <= volume <= 100:
                raise ToolError("volume must be an integer from 0 to 100", code="invalid_input")
            return {"device": device, "volume": volume}
        if self.id == "audio.set_mute":
            muted = arguments.get("muted")
            if not isinstance(muted, bool):
                raise ToolError("muted must be a boolean", code="invalid_input")
            return {"device": device, "muted": muted}
        role = arguments.get("role")
        if role not in {"input", "output"}:
            raise ToolError("role must be input or output", code="invalid_input")
        return {"device": device, "role": role}

    def execute(self, arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        action = _audio_action(self.id)
        role = arguments.get("role")
        volume = arguments.get("volume")
        muted = arguments.get("muted")
        return _applied(
            self._service.apply(
                AudioRequest(
                    action=action,
                    agent_id=self._agent(context),
                    device=str(arguments["device"]),
                    role=role if role in {"input", "output"} else None,
                    volume=volume if isinstance(volume, int) else None,
                    muted=muted if isinstance(muted, bool) else None,
                ),
                {},
                self._environment,
                permitted=True,
            )
        )


class InputActionTool(_ObserverTool):
    def __init__(self, tool_id: str, service: InputService, environment: str) -> None:
        super().__init__(tool_id, environment)
        self._service = service

    def validate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return self._empty(arguments)

    def execute(self, arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        del arguments
        return _applied(
            self._service.apply(
                InputRequest(action=_input_action(self.id), agent_id=self._agent(context)),
                {},
                self._environment,
                permitted=True,
            )
        )


class DisplayInspectTool(_ObserverTool):
    def __init__(self, provider: DisplayProvider, environment: str) -> None:
        super().__init__("display.inspect", environment)
        self._provider = provider

    def validate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return self._empty(arguments)

    def execute(self, arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        del arguments, context
        return self._provider.diagnose().model_dump(mode="json")


class HardwareInspectTool(_ObserverTool):
    def __init__(self, service: HardwareService, environment: str) -> None:
        super().__init__("hardware.inspect", environment)
        self._service = service

    def validate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return self._empty(arguments)

    def execute(self, arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        del arguments, context
        return self._service.inventory().model_dump(mode="json")


class StorageInspectTool(_ObserverTool):
    def __init__(self, service: StorageService, environment: str) -> None:
        super().__init__("storage.inspect", environment)
        self._service = service

    def validate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return self._empty(arguments)

    def execute(self, arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        del arguments, context
        return self._service.inspect().model_dump(mode="json")


def observer_tools(
    *,
    environment: str,
    network: NetworkService,
    audio: AudioService,
    hardware: HardwareService,
    storage: StorageService,
    display: DisplayProvider,
    controls: InputService,
) -> list[_ObserverTool]:
    """The observer actions the gateway can allow."""

    return [
        NetworkScanTool(network, environment),
        NetworkChangeTool("network.connect", network, environment),
        NetworkChangeTool("network.disconnect", network, environment),
        NetworkChangeTool("network.enable", network, environment),
        NetworkChangeTool("network.disable", network, environment),
        AudioChangeTool("audio.set_default", audio, environment),
        AudioChangeTool("audio.set_volume", audio, environment),
        AudioChangeTool("audio.set_mute", audio, environment),
        InputActionTool("input.activate", controls, environment),
        InputActionTool("input.cancel", controls, environment),
        InputActionTool("input.bind", controls, environment),
        DisplayInspectTool(display, environment),
        HardwareInspectTool(hardware, environment),
        StorageInspectTool(storage, environment),
    ]


def _network_action(tool_id: str) -> Literal["connect", "disconnect", "enable", "disable"]:
    if tool_id == "network.connect":
        return "connect"
    if tool_id == "network.disconnect":
        return "disconnect"
    if tool_id == "network.enable":
        return "enable"
    if tool_id == "network.disable":
        return "disable"
    raise ToolError("unknown network action", code="invalid_input")


def _audio_action(tool_id: str) -> Literal["set_default", "set_volume", "set_mute"]:
    if tool_id == "audio.set_default":
        return "set_default"
    if tool_id == "audio.set_volume":
        return "set_volume"
    if tool_id == "audio.set_mute":
        return "set_mute"
    raise ToolError("unknown audio action", code="invalid_input")


def _input_action(tool_id: str) -> Literal["activate", "cancel", "bind"]:
    if tool_id == "input.activate":
        return "activate"
    if tool_id == "input.cancel":
        return "cancel"
    if tool_id == "input.bind":
        return "bind"
    raise ToolError("unknown input action", code="invalid_input")


def _applied(outcome: Any) -> dict[str, Any]:
    if getattr(outcome, "applied", False) is not True:
        raise ToolError(
            str(getattr(outcome, "reason", "observer action failed")), code="not_applied"
        )
    dumped = outcome.model_dump(mode="json")
    if not isinstance(dumped, dict):
        return {"applied": True}
    return dumped
