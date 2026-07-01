"""Offline tests for the pure scheduling core. No network, no Airtable, no clock reads."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from vibersvp.models import Channel, Event, Offset, Rsvp, new_rsvp_alert_key
from vibersvp.scheduler import (
    compute_due_reminders,
    compute_new_rsvp_alerts,
    events_to_complete,
    parse_offsets,
    within_sms_window,
)

UTC = timezone.utc
EVENT_START = datetime(2026, 7, 1, 18, 0, tzinfo=UTC)  # 18:00 UTC
DEFAULT_OFFSETS = [Offset(24 * 60, "24h"), Offset(120, "2h")]


def make_event(**overrides) -> Event:
    base = dict(
        id="evt1",
        name="Fernwood door-knock",
        start=EVENT_START,
        end=None,
        location="1234 Gladstone Ave",
        status="Open",
        reminder_offsets=None,
        notes="",
    )
    base.update(overrides)
    return Event(**base)


def make_rsvp(**overrides) -> Rsvp:
    base = dict(
        id="rsvp1",
        name="Pat Volunteer",
        email="pat@example.com",
        phone="+12505550123",
        event_id="evt1",
        status="Going",
    )
    base.update(overrides)
    return Rsvp(**base)


# --- parse_offsets -----------------------------------------------------------

def test_parse_offsets_units_and_labels():
    parsed = parse_offsets("24h, 2h ,30m,1d")
    assert parsed == [
        Offset(1440, "24h"),
        Offset(120, "2h"),
        Offset(30, "30m"),
        Offset(1440, "1d"),
    ]


def test_parse_offsets_skips_garbage_and_blanks():
    assert parse_offsets("") == []
    assert parse_offsets("2h,,nonsense,5x") == [Offset(120, "2h")]


def test_parse_offsets_channel_suffix():
    parsed = parse_offsets("24h,2h:sms,30m:email")
    assert parsed == [
        Offset(1440, "24h", None),               # bare = every available channel
        Offset(120, "2h", (Channel.SMS,)),        # text-only nudge
        Offset(30, "30m", (Channel.EMAIL,)),      # label drops the suffix
    ]


def test_parse_offsets_rejects_unknown_channel_suffix():
    assert parse_offsets("2h:carrierpigeon") == []


# --- compute_due_reminders ---------------------------------------------------

def test_both_offsets_due_one_hour_before():
    now = datetime(2026, 7, 1, 17, 0, tzinfo=UTC)  # 1h before; 24h and 2h both passed
    due = compute_due_reminders([make_event()], [make_rsvp()], now, DEFAULT_OFFSETS)
    # 2 offsets x 2 channels (email + sms)
    assert len(due) == 4
    assert {(d.offset.label, d.channel) for d in due} == {
        ("24h", Channel.EMAIL),
        ("24h", Channel.SMS),
        ("2h", Channel.EMAIL),
        ("2h", Channel.SMS),
    }


def test_offset_channel_suffix_routes_2h_to_sms_only():
    now = datetime(2026, 7, 1, 17, 0, tzinfo=UTC)  # both 24h and 2h windows open
    offsets = parse_offsets("24h,2h:sms")  # the campaign default
    due = compute_due_reminders([make_event()], [make_rsvp()], now, offsets)
    assert {(d.offset.label, d.channel) for d in due} == {
        ("24h", Channel.EMAIL),
        ("24h", Channel.SMS),
        ("2h", Channel.SMS),  # no ("2h", Channel.EMAIL) — the 2h email is gone
    }


def test_sms_pinned_offset_skipped_when_volunteer_has_no_phone():
    now = datetime(2026, 7, 1, 17, 0, tzinfo=UTC)
    offsets = parse_offsets("2h:sms")
    rsvp = make_rsvp(phone=None)  # email only, but this offset is text-only
    assert compute_due_reminders([make_event()], [rsvp], now, offsets) == []


def test_only_earlier_offset_due():
    now = datetime(2026, 7, 1, 15, 0, tzinfo=UTC)  # 3h before: 24h due, 2h not yet
    due = compute_due_reminders([make_event()], [make_rsvp()], now, DEFAULT_OFFSETS)
    assert {d.offset.label for d in due} == {"24h"}


def test_nothing_due_before_first_window():
    now = datetime(2026, 6, 30, 12, 0, tzinfo=UTC)  # earlier than the 24h send time
    assert compute_due_reminders([make_event()], [make_rsvp()], now, DEFAULT_OFFSETS) == []


def test_nothing_due_after_event_started():
    now = datetime(2026, 7, 1, 19, 0, tzinfo=UTC)  # event already began
    assert compute_due_reminders([make_event()], [make_rsvp()], now, DEFAULT_OFFSETS) == []


def test_inactive_event_skipped():
    now = datetime(2026, 7, 1, 17, 0, tzinfo=UTC)
    event = make_event(status="Cancelled")
    assert compute_due_reminders([event], [make_rsvp()], now, DEFAULT_OFFSETS) == []


def test_non_going_rsvp_skipped():
    now = datetime(2026, 7, 1, 17, 0, tzinfo=UTC)
    rsvp = make_rsvp(status="Not Going")
    assert compute_due_reminders([make_event()], [rsvp], now, DEFAULT_OFFSETS) == []


def test_no_contact_info_gets_nothing():
    now = datetime(2026, 7, 1, 17, 0, tzinfo=UTC)
    rsvp = make_rsvp(email=None, phone=None)  # no way to reach this volunteer
    assert compute_due_reminders([make_event()], [rsvp], now, DEFAULT_OFFSETS) == []


def test_missing_email_falls_back_to_sms_only():
    now = datetime(2026, 7, 1, 17, 0, tzinfo=UTC)
    rsvp = make_rsvp(email=None)  # no email address on file
    due = compute_due_reminders([make_event()], [rsvp], now, DEFAULT_OFFSETS)
    assert {d.channel for d in due} == {Channel.SMS}


def test_per_event_offset_override_wins():
    now = datetime(2026, 7, 1, 17, 30, tzinfo=UTC)  # 30 min before
    event = make_event(reminder_offsets=(Offset(60, "1h"),))
    rsvp = make_rsvp(phone=None)  # email only, to keep it to one record
    due = compute_due_reminders([event], [rsvp], now, DEFAULT_OFFSETS)
    assert [(d.offset.label, d.channel) for d in due] == [("1h", Channel.EMAIL)]


def test_event_without_start_is_skipped():
    now = datetime(2026, 7, 1, 17, 0, tzinfo=UTC)
    event = make_event(start=None)
    assert compute_due_reminders([event], [make_rsvp()], now, DEFAULT_OFFSETS) == []


def test_idempotency_keys_are_distinct_and_stable():
    now = datetime(2026, 7, 1, 17, 0, tzinfo=UTC)
    due = compute_due_reminders([make_event()], [make_rsvp()], now, DEFAULT_OFFSETS)
    keys = [d.key for d in due]
    assert len(keys) == len(set(keys))  # no duplicates
    assert "rsvp1::24h::Email" in keys


# --- events_to_complete ------------------------------------------------------

def test_event_completed_after_end():
    now = datetime(2026, 7, 1, 21, 0, tzinfo=UTC)
    event = make_event(end=datetime(2026, 7, 1, 20, 0, tzinfo=UTC))
    assert [e.id for e in events_to_complete([event], now)] == ["evt1"]


def test_event_not_completed_before_end():
    now = datetime(2026, 7, 1, 19, 0, tzinfo=UTC)  # past start, before end
    event = make_event(end=datetime(2026, 7, 1, 20, 0, tzinfo=UTC))
    assert events_to_complete([event], now) == []


def test_event_completion_falls_back_to_start_when_no_end():
    now = datetime(2026, 7, 1, 18, 30, tzinfo=UTC)  # after start, no end set
    assert [e.id for e in events_to_complete([make_event()], now)] == ["evt1"]


def test_event_not_completed_before_start():
    now = datetime(2026, 7, 1, 17, 0, tzinfo=UTC)  # before start, no end
    assert events_to_complete([make_event()], now) == []


def test_only_open_events_are_completed():
    now = datetime(2026, 7, 2, 0, 0, tzinfo=UTC)  # well past the event
    for status in ("Draft", "Cancelled", "Completed"):
        assert events_to_complete([make_event(status=status)], now) == []


def test_event_without_dates_is_never_completed():
    now = datetime(2026, 7, 2, 0, 0, tzinfo=UTC)
    assert events_to_complete([make_event(start=None, end=None)], now) == []


# --- compute_new_rsvp_alerts -------------------------------------------------

LOOKBACK = timedelta(hours=24)
NOW = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)


def test_new_going_rsvp_within_lookback_alerts():
    rsvp = make_rsvp(created=NOW - timedelta(minutes=10))
    alerts = compute_new_rsvp_alerts([rsvp], [make_event()], NOW, LOOKBACK, set())
    assert len(alerts) == 1
    assert alerts[0].rsvp.id == "rsvp1"
    assert alerts[0].event.id == "evt1"  # event resolved from the RSVP's link
    assert alerts[0].key == "rsvp1::new-rsvp::SMS"


def test_alert_skipped_when_already_sent():
    rsvp = make_rsvp(created=NOW - timedelta(minutes=10))
    already = {new_rsvp_alert_key("rsvp1")}
    assert compute_new_rsvp_alerts([rsvp], [make_event()], NOW, LOOKBACK, already) == []


def test_not_going_rsvp_never_alerts():
    rsvp = make_rsvp(status="Not Going", created=NOW - timedelta(minutes=10))
    assert compute_new_rsvp_alerts([rsvp], [make_event()], NOW, LOOKBACK, set()) == []


def test_old_rsvp_outside_lookback_is_not_new():
    rsvp = make_rsvp(created=NOW - timedelta(hours=25))  # just past the 24h window
    assert compute_new_rsvp_alerts([rsvp], [make_event()], NOW, LOOKBACK, set()) == []


def test_rsvp_without_created_timestamp_is_skipped():
    rsvp = make_rsvp(created=None)  # can't place it in time → not treated as new
    assert compute_new_rsvp_alerts([rsvp], [make_event()], NOW, LOOKBACK, set()) == []


def test_alert_still_fires_when_event_link_missing():
    rsvp = make_rsvp(event_id=None, created=NOW - timedelta(minutes=5))
    alerts = compute_new_rsvp_alerts([rsvp], [make_event()], NOW, LOOKBACK, set())
    assert len(alerts) == 1
    assert alerts[0].event is None


def test_alert_key_is_stable_and_distinct_from_reminder_keys():
    key = new_rsvp_alert_key("rsvp1")
    assert key == "rsvp1::new-rsvp::SMS"
    # never collides with a reminder key, whose middle segment is an offset label
    assert key not in {"rsvp1::24h::SMS", "rsvp1::2h::Email"}


# --- within_sms_window -------------------------------------------------------

def test_sms_window_respects_local_time():
    tz = ZoneInfo("America/Vancouver")
    # 2026-07-01 16:00 UTC == 09:00 PDT (inside 9-21 window)
    assert within_sms_window(datetime(2026, 7, 1, 16, 0, tzinfo=UTC), tz, 9, 21) is True
    # 2026-07-01 06:00 UTC == 23:00 PDT previous day (outside window)
    assert within_sms_window(datetime(2026, 7, 1, 6, 0, tzinfo=UTC), tz, 9, 21) is False
