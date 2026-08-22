"""Runtime configuration, loaded from environment variables (or a local .env).

Only imported by the I/O layer (run.py, airtable.py, notifiers). The pure core
(models, scheduler, templates) never imports this, so tests need no env at all.
"""

from __future__ import annotations

from datetime import timedelta
from functools import cached_property
from zoneinfo import ZoneInfo

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .models import Offset
from .scheduler import parse_offsets

DEFAULT_TIMEZONE = "America/Vancouver"
# The digest's send window is `[start - offset, start)`, and GitHub's scheduled cron only
# fires every ~45-70 min (it drops most of the */15 ticks and stalls for hours overnight),
# so the offset doubles as the drift budget: a window with no run in it drops the digest
# permanently, since we never send once the shift has begun. Measured over 300 runs and 21
# events, a 2h window missed 3 of them and delivered a median of only 1.4h of notice; 3h
# misses 1 and delivers a median of 2.6h. 4h+ buys no extra coverage and only makes the
# heads-up staler, so this is the sweet spot rather than a round number.
DEFAULT_ROSTER_DIGEST_OFFSET = "3h"
DEFAULT_REMINDER_OFFSETS = "24h,2h:sms"
DEFAULT_EMAIL_FROM_NAME = "Jack Sandor Campaign"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Airtable (required) ---
    airtable_api_token: str
    airtable_base_id: str
    events_table: str = "Events"
    rsvps_table: str = "RSVPs"
    reminder_log_table: str = "ReminderLog"

    # --- Email via Resend (required for email reminders) ---
    resend_api_key: str | None = None
    email_from: str | None = None
    email_from_name: str = DEFAULT_EMAIL_FROM_NAME
    email_reply_to: str | None = None

    # --- SMS via Twilio (optional until the number is verified) ---
    twilio_account_sid: str | None = None
    twilio_auth_token: str | None = None
    twilio_from_number: str | None = None

    # --- New-RSVP alerts to the organizer (optional; needs Twilio configured above) ---
    # The organizer's cell (E.164, e.g. +12505550123). Blank disables the alerts.
    jack_phone: str | None = None
    # Only RSVPs created within this window count as "new" — guards the first deploy from
    # texting the whole existing RSVP list. Same m/h/d syntax as reminder offsets.
    new_rsvp_lookback: str = "24h"

    # --- Pre-shift roster digest to the organizer (same jack_phone + Twilio requirement) ---
    # How long before a shift to text the organizer the list of volunteers who RSVP'd
    # 'Going'. Same m/h/d syntax as the reminder offsets. Set to "off" to disable; blank
    # means "use the default" so an empty GitHub Actions variable can't silently kill it.
    roster_digest_offset: str = DEFAULT_ROSTER_DIGEST_OFFSET

    # --- Behaviour ---
    # "2h:sms" makes the 2h nudge text-only; the 24h reminder still goes on email + SMS.
    # Blank means "use the default", not "no reminders" — see the validator below.
    default_reminder_offsets: str = DEFAULT_REMINDER_OFFSETS
    timezone: str = DEFAULT_TIMEZONE
    campaign_name: str = "Jack Sandor for Victoria"
    campaign_contact: str = "the campaign team"
    sms_quiet_start_hour: int = 9
    sms_quiet_end_hour: int = 21

    @field_validator("timezone", mode="before")
    @classmethod
    def _default_blank_timezone(cls, v: object) -> object:
        """A set-but-empty TIMEZONE env var overrides the field default with "",
        which then crashes ZoneInfo(""). Treat blank/whitespace as unset."""
        if v is None or (isinstance(v, str) and not v.strip()):
            return DEFAULT_TIMEZONE
        return v.strip() if isinstance(v, str) else v

    @field_validator("email_from_name", mode="before")
    @classmethod
    def _default_blank_email_from_name(cls, v: object) -> object:
        """Same blank-env-var trap as TIMEZONE, and it breaks every email send.

        `EMAIL_FROM_NAME: ${{ vars.EMAIL_FROM_NAME }}` sets the env var to "" when the
        Actions variable doesn't exist, overriding this field's default. The notifier then
        composes `from` as `" <hello@example.com>"` — a leading space and an empty display
        name — which Resend rejects with "Invalid `from` field", so no email goes out at
        all. Treat blank as unset. (The notifier also drops the name when it's blank, so
        neither layer alone can produce that malformed header.)
        """
        if v is None or (isinstance(v, str) and not v.strip()):
            return DEFAULT_EMAIL_FROM_NAME
        return v.strip() if isinstance(v, str) else v

    @field_validator("roster_digest_offset", mode="before")
    @classmethod
    def _default_blank_roster_digest_offset(cls, v: object) -> object:
        """Blank means "unset", not "disabled" — a GitHub Actions variable that was never
        created arrives as "", and that shouldn't quietly turn the digest off. Use "off"."""
        if v is None or (isinstance(v, str) and not v.strip()):
            return DEFAULT_ROSTER_DIGEST_OFFSET
        return v.strip() if isinstance(v, str) else v

    @field_validator("default_reminder_offsets", mode="before")
    @classmethod
    def _default_blank_reminder_offsets(cls, v: object) -> object:
        """Same trap as TIMEZONE and ROSTER_DIGEST_OFFSET, with the widest blast radius.

        `DEFAULT_REMINDER_OFFSETS: ${{ vars.DEFAULT_REMINDER_OFFSETS }}` in the workflow sets
        the env var to "" when the Actions variable doesn't exist, which overrides this
        field's default. "" then parses to an empty offset list, and an empty offset list
        means *every* volunteer reminder is silently skipped — no error, no log line, just
        a worker that reports `due=0` forever. Treat blank as unset.

        There's deliberately no "off" escape hatch here (unlike the roster digest): sending
        no reminders at all is never the intent, and disabling the job means disabling the
        workflow. An offsets string that's non-blank but entirely unparseable still yields
        an empty list — that's a typo worth surfacing, not a default worth papering over.
        """
        if v is None or (isinstance(v, str) and not v.strip()):
            return DEFAULT_REMINDER_OFFSETS
        return v.strip() if isinstance(v, str) else v

    @property
    def email_enabled(self) -> bool:
        return bool(self.resend_api_key and self.email_from)

    @property
    def sms_enabled(self) -> bool:
        return bool(self.twilio_account_sid and self.twilio_auth_token and self.twilio_from_number)

    @property
    def new_rsvp_alerts_enabled(self) -> bool:
        """We can only text the organizer if SMS is wired up and we know their number."""
        return bool(self.sms_enabled and self.jack_phone)

    @property
    def roster_digest_enabled(self) -> bool:
        """Needs the same SMS wiring as the new-RSVP alerts, plus a usable lead time."""
        return bool(self.sms_enabled and self.jack_phone and self.roster_digest_lead)

    @cached_property
    def roster_digest_lead(self) -> Offset | None:
        """The digest lead time as an Offset, or None when it's "off" (or unparseable)."""
        offsets = parse_offsets(self.roster_digest_offset)
        return offsets[0] if offsets else None

    @cached_property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    @cached_property
    def default_offsets(self) -> list[Offset]:
        return parse_offsets(self.default_reminder_offsets)

    @cached_property
    def new_rsvp_lookback_delta(self) -> timedelta:
        """Parse new_rsvp_lookback ('24h'); fall back to 24h if unset or unparseable."""
        offsets = parse_offsets(self.new_rsvp_lookback)
        return timedelta(minutes=offsets[0].minutes) if offsets else timedelta(hours=24)
