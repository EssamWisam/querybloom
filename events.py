"""Small event primitives for streamable ABSTAT pipelines."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class PipelineEvent:
    """A JSON-friendly event emitted by long-running ABSTAT steps."""

    type: str
    stage: str
    message: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    run_id: Optional[str] = None
    timestamp: str = field(default_factory=_utc_now)

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "type": self.type,
            "stage": self.stage,
            "message": self.message,
            "data": self.data,
            "timestamp": self.timestamp,
        }
        if self.run_id is not None:
            payload["run_id"] = self.run_id
        return payload


EventSink = Callable[[PipelineEvent], None]


def emit_event(
    event_sink: EventSink | None,
    event_type: str,
    stage: str,
    message: str = "",
    data: dict[str, Any] | None = None,
    run_id: str | None = None,
) -> None:
    """Emit an event if a sink is configured, ignoring sink failures."""
    if event_sink is None:
        return
    try:
        event_sink(
            PipelineEvent(
                type=event_type,
                stage=stage,
                message=message,
                data=data or {},
                run_id=run_id,
            )
        )
    except Exception:
        return
