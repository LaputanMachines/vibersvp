"""Plain data models. No I/O, no third-party deps — safe to import in tests."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class Channel(str, Enum):
    EMAIL = "Email"
    SMS = "SMS"


@dataclass(frozen=True)
class Offset:
    """A reminder lead time, e.g. 2 hours before an event."""

    minutes: int
    label: str  # the original token ("24h", "2h", "30m") — used in the idempotency key


@dataclass(frozen=True)
class Event:
    id: str
    name: str
    start: datetime | None  # tz-aware (UTC); None if the Airtable row has no Start
    end: datetime | None
    location: str
    status: str
    # Per-event override of the reminder schedule; None means "use the config default".
    reminder_offsets: tuple[Offset, ...] | None
    notes: str


@dataclass(frozen=True)
class Rsvp:
    id: str
    name: str
    email: str | None
    phone: str | None
    event_id: str | None
    status: str


@dataclass(frozen=True)
class DueReminder:
    """One reminder that should be sent now, on one channel, to one volunteer."""

    rsvp: Rsvp
    event: Event
    offset: Offset
    channel: Channel

    @property
    def key(self) -> str:
        """Stable idempotency key — one send per (rsvp, offset, channel), ever."""
        return reminder_key(self.rsvp.id, self.offset.label, self.channel)


def reminder_key(rsvp_id: str, offset_label: str, channel: Channel) -> str:
    return f"{rsvp_id}::{offset_label}::{channel.value}"
