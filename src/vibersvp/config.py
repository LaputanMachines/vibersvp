"""Runtime configuration, loaded from environment variables (or a local .env).

Only imported by the I/O layer (run.py, airtable.py, notifiers). The pure core
(models, scheduler, templates) never imports this, so tests need no env at all.
"""

from __future__ import annotations

from functools import cached_property
from zoneinfo import ZoneInfo

from pydantic_settings import BaseSettings, SettingsConfigDict

from .models import Offset
from .scheduler import parse_offsets


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
    email_from_name: str = "Jack Sandor Campaign"
    email_reply_to: str | None = None

    # --- SMS via Twilio (optional until the number is verified) ---
    twilio_account_sid: str | None = None
    twilio_auth_token: str | None = None
    twilio_from_number: str | None = None

    # --- Behaviour ---
    default_reminder_offsets: str = "24h,2h"
    timezone: str = "America/Vancouver"
    campaign_name: str = "Jack Sandor for Victoria"
    campaign_contact: str = "the campaign team"
    sms_quiet_start_hour: int = 9
    sms_quiet_end_hour: int = 21

    @property
    def email_enabled(self) -> bool:
        return bool(self.resend_api_key and self.email_from)

    @property
    def sms_enabled(self) -> bool:
        return bool(self.twilio_account_sid and self.twilio_auth_token and self.twilio_from_number)

    @cached_property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    @cached_property
    def default_offsets(self) -> list[Offset]:
        return parse_offsets(self.default_reminder_offsets)
