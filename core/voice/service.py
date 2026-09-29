"""Voice control that stays silent without permission and a provider.

No audio device is opened. ``listen`` returns before any provider call unless
the permission decision is ALLOW, and the built-in policy denies transmission.
"""

from __future__ import annotations

from core.permissions.evaluator import PermissionEvaluator
from core.permissions.policies import PermissionDecision, PermissionRequest, PermissionResult


class VoiceService:
    """Report voice availability and refuse to capture audio by default."""

    def __init__(self, evaluator: PermissionEvaluator, *, environment: str) -> None:
        self._evaluator = evaluator
        self._environment = environment
        self.provider_available = False
        self.hardware_available = False

    def status(self) -> dict[str, object]:
        decision = self._decision()
        return {
            "provider": "available" if self.provider_available else "unavailable",
            "hardware": "available" if self.hardware_available else "unavailable",
            "permission": decision.decision.value,
            "listening": False,
            "reason": "no voice provider or audio hardware is configured",
        }

    def listen(self) -> dict[str, object]:
        decision = self._decision()
        if decision.decision is not PermissionDecision.ALLOW:
            return {
                "listening": False,
                "audio": False,
                "permission": decision.decision.value,
                "reason": decision.reason,
            }
        if not self.provider_available or not self.hardware_available:
            return {
                "listening": False,
                "audio": False,
                "permission": decision.decision.value,
                "provider": "unavailable",
                "hardware": "unavailable",
                "reason": "voice provider or audio hardware is unavailable",
            }
        return {"listening": False, "audio": False, "reason": "voice capture is not implemented"}

    def _decision(self) -> PermissionResult:
        return self._evaluator.evaluate(
            PermissionRequest(
                tool_id="voice.transmit",
                grants={"voice": ["transmit"]},
                environment=self._environment,
                workspace_root=".",
            )
        )
