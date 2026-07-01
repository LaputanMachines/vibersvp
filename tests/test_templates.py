"""Offline tests for message rendering."""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from vibersvp.models import Event, Rsvp
from vibersvp.templates import (
    MessageContext,
    render_email,
    render_new_rsvp_alert,
    render_sms,
)

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


def test_new_rsvp_alert_names_the_volunteer_and_event():
    alert = render_new_rsvp_alert(RSVP, EVENT, CTX)
    assert "New RSVP" in alert
    assert "Pat Volunteer" in alert
    assert "Fernwood door-knock" in alert
    assert "11:00 AM" in alert  # event time, in the campaign's local zone
    assert "pat@example.com" in alert  # contact so Jack can follow up
    # operational message to the organizer's own phone — no volunteer-facing opt-out
    assert "STOP" not in alert


def test_new_rsvp_alert_handles_missing_event():
    alert = render_new_rsvp_alert(RSVP, None, CTX)
    assert "Pat Volunteer" in alert
    assert "a shift" in alert  # graceful fallback when no event is linked
