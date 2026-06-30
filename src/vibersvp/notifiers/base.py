"""Common result type shared by all notifiers. Pure — no third-party imports."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SendResult:
    ok: bool
    message_id: str | None = None
    error: str | None = None

    @classmethod
    def sent(cls, message_id: str | None) -> "SendResult":
        return cls(ok=True, message_id=message_id)

    @classmethod
    def failed(cls, error: str) -> "SendResult":
        return cls(ok=False, error=error)
