"""Tests for the Airtable record → model mapping. No network: we call the pure
static mapper directly with hand-built record dicts (the shape pyairtable returns)."""

from __future__ import annotations

from vibersvp.airtable import AirtableRepo


def _record(**fields) -> dict:
    return {"id": "rec123", "fields": fields}


def test_multi_event_rsvp_fans_out_one_per_event():
    # One submission linked to three shifts → three Rsvps, same record id, one per event.
    record = _record(
        Name="Christian",
        Email="christian@example.com",
        Phone="+12505550123",
        Event=["evtA", "evtB", "evtC"],
        Status="Going",
        Created="2026-07-05T01:08:31.000Z",
    )
    rsvps = AirtableRepo._to_rsvps(record)
    assert [r.event_id for r in rsvps] == ["evtA", "evtB", "evtC"]
    assert {r.id for r in rsvps} == {"rec123"}  # same underlying record
    assert {r.name for r in rsvps} == {"Christian"}
    assert {r.status for r in rsvps} == {"Going"}


def test_single_event_rsvp_yields_one():
    record = _record(Name="Pat", Event=["evtA"], Status="Going")
    rsvps = AirtableRepo._to_rsvps(record)
    assert len(rsvps) == 1
    assert rsvps[0].event_id == "evtA"


def test_rsvp_without_event_still_yields_one_with_no_event():
    record = _record(Name="Pat", Status="Going")  # no Event link
    rsvps = AirtableRepo._to_rsvps(record)
    assert len(rsvps) == 1
    assert rsvps[0].event_id is None


def test_blank_contact_fields_become_none():
    record = _record(Name="Pat", Email="", Phone="", Event=["evtA"], Status="Going")
    (rsvp,) = AirtableRepo._to_rsvps(record)
    assert rsvp.email is None
    assert rsvp.phone is None
