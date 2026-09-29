"""Structured messages between agents."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from core.events.bus import EventBus


class AgentMessage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    sender: str
    recipient: str
    task_id: str | None = None
    content: dict[str, object] = Field(default_factory=dict)
    timestamp: datetime


class AgentMailbox:
    """Deliver messages and publish them as events."""

    def __init__(self, events: EventBus) -> None:
        self._events = events
        self._messages: list[AgentMessage] = []

    def send(
        self,
        *,
        sender: str,
        recipient: str,
        content: dict[str, object],
        task_id: str | None = None,
    ) -> AgentMessage:
        message = AgentMessage(
            id=str(uuid4()),
            sender=sender,
            recipient=recipient,
            task_id=task_id,
            content=dict(content),
            timestamp=datetime.now(UTC),
        )
        self._messages.append(message)
        self._events.publish(
            "agent.message",
            task_id=task_id,
            agent_id=sender,
            payload={"recipient": recipient, "id": message.id},
        )
        return message

    def inbox(self, agent_id: str) -> list[AgentMessage]:
        return [message for message in self._messages if message.recipient == agent_id]
