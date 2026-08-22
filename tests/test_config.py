"""Tests for Settings parsing — in particular the blank-env-var guards.

The workflow passes every tunable as `${{ vars.X }}`. An Actions variable that was never
created arrives as a set-but-empty env var, which overrides the field default rather than
falling back to it. Each guard below exists because that swallowed a whole feature once.

`_env_file=None` keeps these hermetic: no developer's local .env leaks in.
"""

from __future__ import annotations

from datetime import timedelta

from vibersvp.config import (
    DEFAULT_EMAIL_FROM_NAME,
    DEFAULT_REMINDER_OFFSETS,
    DEFAULT_ROSTER_DIGEST_OFFSET,
    DEFAULT_TIMEZONE,
    Settings,
)


def make_settings(**overrides) -> Settings:
    base = dict(airtable_api_token="pat_test", airtable_base_id="appTest")
    base.update(overrides)
    return Settings(_env_file=None, **base)


# --- email_from_name ---------------------------------------------------------

def test_blank_email_from_name_falls_back_to_the_default():
    # "" composes the Resend `from` as " <addr>", which the API rejects with
    # "Invalid `from` field" — so a missing Actions variable killed every email send.
    assert make_settings(email_from_name="").email_from_name == DEFAULT_EMAIL_FROM_NAME


def test_whitespace_email_from_name_falls_back_to_the_default():
    assert make_settings(email_from_name="   ").email_from_name == DEFAULT_EMAIL_FROM_NAME


def test_email_from_name_is_stripped():
    assert make_settings(email_from_name="  Jack Sandor  ").email_from_name == "Jack Sandor"


def test_explicit_email_from_name_wins_over_the_default():
    assert make_settings(email_from_name="Jack Sandor").email_from_name == "Jack Sandor"


# --- default_reminder_offsets ------------------------------------------------

def test_blank_reminder_offsets_falls_back_to_the_default():
    # The regression that mattered: "" parsed to [], and an empty offset list means every
    # volunteer reminder is skipped silently — the worker just reports due=0 forever.
    settings = make_settings(default_reminder_offsets="")
    assert settings.default_reminder_offsets == DEFAULT_REMINDER_OFFSETS
    assert [o.label for o in settings.default_offsets] == ["24h", "2h"]


def test_whitespace_reminder_offsets_falls_back_to_the_default():
    assert make_settings(default_reminder_offsets="   ").default_offsets != []


def test_explicit_reminder_offsets_win_over_the_default():
    settings = make_settings(default_reminder_offsets="48h,30m:sms")
    assert [(o.label, o.minutes) for o in settings.default_offsets] == [("48h", 2880), ("30m", 30)]


def test_unparseable_reminder_offsets_are_not_papered_over():
    # Non-blank but garbage stays empty on purpose: that's a typo to surface, not a
    # missing variable to default. Only blank means "unset".
    assert make_settings(default_reminder_offsets="tomorrow").default_offsets == []


# --- roster_digest_offset ----------------------------------------------------

def test_blank_roster_digest_offset_falls_back_to_the_default():
    settings = make_settings(roster_digest_offset="")
    assert settings.roster_digest_offset == DEFAULT_ROSTER_DIGEST_OFFSET
    assert settings.roster_digest_lead.label == DEFAULT_ROSTER_DIGEST_OFFSET


def test_roster_digest_off_disables_the_digest():
    # "off" is the only way to turn it off — blank must not do it.
    settings = make_settings(roster_digest_offset="off")
    assert settings.roster_digest_lead is None
    assert settings.roster_digest_enabled is False


# --- timezone ----------------------------------------------------------------

def test_blank_timezone_falls_back_to_the_default():
    assert str(make_settings(timezone="").tz) == DEFAULT_TIMEZONE


# --- new_rsvp_lookback -------------------------------------------------------

def test_blank_new_rsvp_lookback_falls_back_to_24h():
    # Guarded inside the property rather than by a validator, but same requirement.
    assert make_settings(new_rsvp_lookback="").new_rsvp_lookback_delta == timedelta(hours=24)


# --- feature gating ----------------------------------------------------------

def test_organizer_features_need_both_twilio_and_a_phone_number():
    twilio = dict(twilio_account_sid="AC1", twilio_auth_token="tok", twilio_from_number="+15551112222")
    assert make_settings(**twilio).new_rsvp_alerts_enabled is False  # no jack_phone
    assert make_settings(jack_phone="+12505550123").roster_digest_enabled is False  # no Twilio
    both = make_settings(jack_phone="+12505550123", **twilio)
    assert both.new_rsvp_alerts_enabled is True
    assert both.roster_digest_enabled is True
