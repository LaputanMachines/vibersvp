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
    # When the RSVP record was created (Airtable "Created time" field), tz-aware UTC.
    # None when the field is absent; new-RSVP alerts need it to tell fresh signups apart.
    created: datetime | None = None


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


# Pseudo-"offset" label for the one-off text we send the organizer when someone new RSVPs.
# It rides the same ReminderLog idempotency machinery as reminders — the label just keeps
# its keys from colliding with real reminder offsets ("24h", "2h", …).
NEW_RSVP_OFFSET_LABEL = "new-rsvp"


@dataclass(frozen=True)
class NewRsvpAlert:
    """A heads-up to the organizer that a volunteer just RSVP'd 'Going'."""

    rsvp: Rsvp
    event: Event | None  # None if the RSVP isn't linked to an event (or it was deleted)

    @property
    def key(self) -> str:
        """Stable idempotency key — the organizer is alerted once per RSVP, ever."""
        return new_rsvp_alert_key(self.rsvp.id)


def reminder_key(rsvp_id: str, offset_label: str, channel: Channel) -> str:
    return f"{rsvp_id}::{offset_label}::{channel.value}"


def new_rsvp_alert_key(rsvp_id: str) -> str:
    return reminder_key(rsvp_id, NEW_RSVP_OFFSET_LABEL, Channel.SMS)
