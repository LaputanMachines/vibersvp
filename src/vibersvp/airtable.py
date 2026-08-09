"""Airtable read/write layer (the only place pyairtable is used).

Maps Airtable records to the plain models in ``models.py`` and back. The idempotency
check is done in memory: we load the set of already-sent reminder keys once per run
(the log table is small) rather than querying per reminder.
"""

from __future__ import annotations

from datetime import datetime, timezone

from pyairtable import Api

from .config import Settings
from .models import Channel, Event, Rsvp
from .scheduler import COMPLETED_STATUS, parse_offsets


def _parse_dt(value: str | None) -> datetime | None:
    """Parse an Airtable ISO timestamp to a tz-aware UTC datetime."""
    if not value:
        return None
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class AirtableRepo:
    def __init__(self, settings: Settings):
        self.settings = settings
        api = Api(settings.airtable_api_token)
        base = settings.airtable_base_id
        self._events = api.table(base, settings.events_table)
        self._rsvps = api.table(base, settings.rsvps_table)
        self._log = api.table(base, settings.reminder_log_table)

    # --- reads ---------------------------------------------------------------

    def load_events(self) -> list[Event]:
        return [self._to_event(r) for r in self._events.all()]

    def load_rsvps(self) -> list[Rsvp]:
        rsvps: list[Rsvp] = []
        for record in self._rsvps.all():
            rsvps.extend(self._to_rsvps(record))
        return rsvps

    def load_sent_keys(self) -> set[str]:
        """Keys of reminders already successfully sent — used to dedupe before sending."""
        rows = self._log.all(fields=["Key", "Status"])
        return {
            f["Key"]
            for r in rows
            if (f := r.get("fields", {})).get("Status") == "Sent" and f.get("Key")
        }

    @staticmethod
    def _to_event(record: dict) -> Event:
        f = record.get("fields", {})
        offsets_text = f.get("Reminder offsets")
        parsed = parse_offsets(offsets_text) if offsets_text else None
        return Event(
            id=record["id"],
            name=f.get("Name", ""),
            start=_parse_dt(f.get("Start")),
            end=_parse_dt(f.get("End")),
            location=f.get("Location", ""),
            status=f.get("Status", ""),
            reminder_offsets=tuple(parsed) if parsed else None,
            notes=f.get("Notes", ""),
        )

    @staticmethod
    def _to_rsvps(record: dict) -> list[Rsvp]:
        """Map one Airtable RSVP record to one `Rsvp` *per linked event*.

        Airtable's `Event` link is multi-valued: a volunteer can RSVP to several shifts in
        a single form submission, producing one record with N linked events. We fan that
        record out into N `Rsvp` objects (same record id, different `event_id`) so each
        event gets its own reminders and its own organizer alert. A record with no event
        link still yields one `Rsvp` (event_id=None) so it can trigger a new-RSVP alert.
        """
        f = record.get("fields", {})
        event_links = f.get("Event") or []
        common = dict(
            id=record["id"],
            name=f.get("Name", ""),
            email=(f.get("Email") or None),
            phone=(f.get("Phone") or None),
            status=f.get("Status", ""),
            created=_parse_dt(f.get("Created")),
        )
        if not event_links:
            return [Rsvp(event_id=None, **common)]
        return [Rsvp(event_id=event_id, **common) for event_id in event_links]

    # --- writes --------------------------------------------------------------

    def log_reminder(
        self,
        *,
        key: str,
        rsvp_id: str | None,
        event_id: str | None,
        offset_label: str,
        channel: Channel,
        status: str,
        sent_at: datetime,
        provider_message_id: str | None = None,
        error: str | None = None,
    ) -> None:
        fields = {
            "Key": key,
            "Offset": offset_label,
            "Channel": channel.value,
            "Sent at": sent_at.isoformat(),
            "Status": status,
            "Provider message id": provider_message_id or "",
            "Error": error or "",
        }
        # Only set a link when we actually have one (Airtable rejects a link array
        # containing null): new-RSVP alerts may have no event, and a roster digest is
        # about a whole event, so it has no single RSVP.
        if rsvp_id:
            fields["RSVP"] = [rsvp_id]
        if event_id:
            fields["Event"] = [event_id]
        self._log.create(fields)

    def mark_event_completed(self, event_id: str) -> None:
        """Flip an event's Status to Completed — called once its date has passed."""
        self._events.update(event_id, {"Status": COMPLETED_STATUS})
