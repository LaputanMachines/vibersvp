"""Pure scheduling logic. No I/O, no clock reads — `now` is always passed in.

This is the heart of the worker and the part that's unit-tested. Keeping it pure
(deterministic, side-effect free) is what makes the GitHub Actions cron drift safe:
the same inputs always produce the same set of due reminders.
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .models import Channel, DueReminder, Event, Offset, Rsvp

# Events only get reminders while they're live and accepting volunteers.
ACTIVE_EVENT_STATUSES = frozenset({"Open", "Full"})
GOING_STATUS = "Going"

_OFFSET_RE = re.compile(r"^\s*(\d+)\s*([mhd])\s*$", re.IGNORECASE)
_UNIT_MINUTES = {"m": 1, "h": 60, "d": 60 * 24}


def parse_offsets(text: str) -> list[Offset]:
    """'24h,2h' -> [Offset(1440,'24h'), Offset(120,'2h')]. Bad tokens are skipped."""
    offsets: list[Offset] = []
    for raw in (text or "").split(","):
        token = raw.strip()
        if not token:
            continue
        m = _OFFSET_RE.match(token)
        if not m:
            continue
        value, unit = int(m.group(1)), m.group(2).lower()
        offsets.append(Offset(minutes=value * _UNIT_MINUTES[unit], label=token))
    return offsets


def channels_for(rsvp: Rsvp) -> list[Channel]:
    """Which channels this volunteer can be reached on, honouring per-channel consent."""
    channels: list[Channel] = []
    if rsvp.email and rsvp.email_consent:
        channels.append(Channel.EMAIL)
    if rsvp.phone and rsvp.sms_consent:
        channels.append(Channel.SMS)
    return channels


def compute_due_reminders(
    events: list[Event],
    rsvps: list[Rsvp],
    now: datetime,
    default_offsets: list[Offset],
) -> list[DueReminder]:
    """Return every reminder whose send-time has arrived but whose event hasn't started.

    An offset is "due" when `event.start - offset <= now < event.start`. Because the
    window stays open until the event begins, a late or skipped cron run still sends the
    reminder on the next run (just later) — and the idempotency key prevents duplicates.
    """
    going_by_event: dict[str, list[Rsvp]] = defaultdict(list)
    for rsvp in rsvps:
        if rsvp.status == GOING_STATUS and rsvp.event_id:
            going_by_event[rsvp.event_id].append(rsvp)

    due: list[DueReminder] = []
    for event in events:
        if event.status not in ACTIVE_EVENT_STATUSES:
            continue
        if event.start is None or now >= event.start:
            continue

        offsets = list(event.reminder_offsets) if event.reminder_offsets else default_offsets
        attendees = going_by_event.get(event.id, [])
        if not attendees:
            continue

        for offset in offsets:
            send_at = event.start - timedelta(minutes=offset.minutes)
            if not (send_at <= now < event.start):
                continue
            for rsvp in attendees:
                for channel in channels_for(rsvp):
                    due.append(DueReminder(rsvp=rsvp, event=event, offset=offset, channel=channel))
    return due


def within_sms_window(now: datetime, tz: ZoneInfo, start_hour: int, end_hour: int) -> bool:
    """True if `now` (converted to local time) is inside the allowed SMS hours [start, end)."""
    local_hour = now.astimezone(tz).hour
    return start_hour <= local_hour < end_hour
