"""Offline tests for message rendering."""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from vibersvp.models import Event, Rsvp
from vibersvp.templates import MessageContext, render_email, render_sms

UTC = timezone.utc

CTX = MessageContext(
    campaign_name="Jack Sandor for Victoria",
    campaign_contact="the campaign team",
    tz=ZoneInfo("America/Vancouver"),
)

EVENT = Event(
    id="evt1",
    name="Fernwood door-knock",
    start=datetime(2026, 7, 1, 18, 0, tzinfo=UTC),  # 11:00 AM PDT
    end=None,
    location="1234 Gladstone Ave",
    status="Open",
    reminder_offsets=None,
    notes="Wear comfortable shoes.",
)

RSVP = Rsvp(
    id="rsvp1",
    name="Pat Volunteer",
    email="pat@example.com",
    phone="+12505550123",
    event_id="evt1",
    status="Going",
)


def test_email_includes_key_details_and_optout():
    email = render_email(EVENT, RSVP, CTX)
    assert "Fernwood door-knock" in email.subject
    for body in (email.text, email.html):
        assert "Pat" in body
        assert "1234 Gladstone Ave" in body
        assert "Jack Sandor for Victoria" in body
        assert "Wear comfortable shoes." in body
        assert "stop reminders" in body.lower()
    # 18:00 UTC is 11:00 AM Pacific
    assert "11:00 AM" in email.text


def test_sms_is_short_identified_and_has_stop():
    sms = render_sms(EVENT, RSVP, CTX)
    assert "Jack Sandor for Victoria" in sms
    assert "Fernwood door-knock" in sms
    assert "STOP" in sms
