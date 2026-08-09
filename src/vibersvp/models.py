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
    label: str  # the duration token ("24h", "2h", "30m") — used in the idempotency key
    # Which channels this offset sends on. None means "every channel the volunteer has
    # contact info for"; a tuple restricts it (e.g. (Channel.SMS,) for a text-only nudge).
    channels: tuple["Channel", ...] | None = None


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
        """Stable idempotency key — one send per (rsvp, event, offset, channel), ever."""
        return reminder_key(self.rsvp.id, self.event.id, self.offset.label, self.channel)


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
        """Stable idempotency key — the organizer is alerted once per (RSVP, event), ever.

        Keyed on the RSVP record *and* its event so a single record linked to several
        events yields a distinct alert per event (Airtable's Event link is multi-valued).
        Uses ``rsvp.event_id`` (not ``event.id``) so a dangling link to a deleted event
        still produces a stable key that matches the dedup check in the scheduler.
        """
        return new_rsvp_alert_key(self.rsvp.id, self.rsvp.event_id)


# Prefix for the pseudo-"offset" label of the pre-shift roster digest. The digest has its
# own lead time ("2h"), so the prefix is what keeps its key from colliding with the
# volunteers' own "2h" reminder for the same event.
ROSTER_OFFSET_PREFIX = "roster-"

# Placeholder RSVP segment for the roster digest: it's about a whole event, not one
# volunteer, so there's no RSVP record id to key on. Airtable record ids always start
# with "rec", so this can never collide with a real one.
NO_RSVP_SEGMENT = "roster"


@dataclass(frozen=True)
class RosterDigest:
    """The pre-shift roster texted to the organizer: who's coming to this event."""

    event: Event
    attendees: tuple[Rsvp, ...]  # 'Going' RSVPs, name-sorted; empty means nobody signed up
    offset: Offset  # the digest's own lead time, independent of the volunteer offsets

    @property
    def offset_label(self) -> str:
        """Label written to ReminderLog's Offset column, e.g. 'roster-2h'."""
        return ROSTER_OFFSET_PREFIX + self.offset.label

    @property
    def key(self) -> str:
        """Stable idempotency key — one digest per (event, lead time), ever."""
        return roster_digest_key(self.event.id, self.offset.label)


# Placeholder event segment for an RSVP with no linked event, so its key is still
# well-formed (four segments) and never collides with a real event id.
NO_EVENT_SEGMENT = "no-event"


def reminder_key(rsvp_id: str, event_id: str | None, offset_label: str, channel: Channel) -> str:
    return f"{rsvp_id}::{event_id or NO_EVENT_SEGMENT}::{offset_label}::{channel.value}"


def new_rsvp_alert_key(rsvp_id: str, event_id: str | None) -> str:
    return reminder_key(rsvp_id, event_id, NEW_RSVP_OFFSET_LABEL, Channel.SMS)


def roster_digest_key(event_id: str, offset_label: str) -> str:
    return reminder_key(NO_RSVP_SEGMENT, event_id, ROSTER_OFFSET_PREFIX + offset_label, Channel.SMS)
