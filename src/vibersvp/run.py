"""Entry point: send every reminder that's due right now, exactly once.

Run shape (one shot, then exit — GitHub Actions calls this on a schedule):

    python -m vibersvp.run --once            # send for real
    python -m vibersvp.run --once --dry-run  # read data, log what *would* send, send nothing
    python -m vibersvp.run --now 2026-07-01T17:00:00Z   # override the clock for testing

Safe to run repeatedly: each (rsvp, offset, channel) is sent once, tracked in ReminderLog.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone

from .airtable import AirtableRepo
from .config import Settings
from .models import Channel
from .scheduler import compute_due_reminders, within_sms_window
from .templates import MessageContext, render_email, render_sms

logger = logging.getLogger("vibersvp")


def _parse_now(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="vibersvp", description="Send due canvassing RSVP reminders.")
    parser.add_argument("--once", action="store_true", help="Process due reminders once and exit (default behaviour).")
    parser.add_argument("--dry-run", action="store_true", help="Log what would send; send nothing and write no log rows.")
    parser.add_argument("--now", help="Override 'now' as ISO 8601 (testing). Defaults to current UTC time.")
    parser.add_argument("-v", "--verbose", action="store_true", help="Debug logging.")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    settings = Settings()  # raises a clear error if required Airtable env vars are missing
    now = _parse_now(args.now)

    repo = AirtableRepo(settings)
    events = repo.load_events()
    rsvps = repo.load_rsvps()
    due = compute_due_reminders(events, rsvps, now, settings.default_offsets)
    logger.info(
        "now=%s | events=%d rsvps=%d due=%d | email=%s sms=%s dry_run=%s",
        now.isoformat(), len(events), len(rsvps), len(due),
        settings.email_enabled, settings.sms_enabled, args.dry_run,
    )
    if not due:
        return 0

    sent_keys: set[str] = set() if args.dry_run else repo.load_sent_keys()
    email_notifier = _build_email_notifier(settings)
    sms_notifier = _build_sms_notifier(settings)
    ctx = MessageContext(settings.campaign_name, settings.campaign_contact, settings.tz)

    counts = {"sent": 0, "would_send": 0, "dup": 0, "quiet": 0, "unconfigured": 0, "failed": 0}

    for reminder in due:
        key = reminder.key
        if key in sent_keys:
            counts["dup"] += 1
            continue

        rsvp, event, channel = reminder.rsvp, reminder.event, reminder.channel

        if channel is Channel.EMAIL and email_notifier is None:
            logger.info("SKIP email not configured: %s", key)
            counts["unconfigured"] += 1
            continue
        if channel is Channel.SMS and sms_notifier is None:
            logger.info("SKIP sms not configured: %s", key)
            counts["unconfigured"] += 1
            continue

        # SMS quiet hours: don't send now; a later run inside the window will pick it up.
        if channel is Channel.SMS and not within_sms_window(
            now, settings.tz, settings.sms_quiet_start_hour, settings.sms_quiet_end_hour
        ):
            logger.info("DEFER sms (quiet hours): %s", key)
            counts["quiet"] += 1
            continue

        if args.dry_run:
            target = rsvp.email if channel is Channel.EMAIL else rsvp.phone
            logger.info("WOULD SEND %s -> %s | %s | %s before", channel.value, target, event.name, reminder.offset.label)
            counts["would_send"] += 1
            continue

        result = _send(channel, event, rsvp, ctx, email_notifier, sms_notifier)
        status = "Sent" if result.ok else "Failed"
        repo.log_reminder(
            key=key,
            rsvp_id=rsvp.id,
            event_id=event.id,
            offset_label=reminder.offset.label,
            channel=channel,
            status=status,
            sent_at=now,
            provider_message_id=result.message_id,
            error=result.error,
        )
        if result.ok:
            sent_keys.add(key)  # guard against a duplicate within this same run
            counts["sent"] += 1
            logger.info("SENT %s -> %s (%s) msg_id=%s", channel.value, rsvp.name, event.name, result.message_id)
        else:
            counts["failed"] += 1
            logger.error("FAILED %s -> %s (%s): %s", channel.value, rsvp.name, event.name, result.error)

    logger.info("done: %s", counts)
    return 1 if counts["failed"] else 0


def _build_email_notifier(settings: Settings):
    if not settings.email_enabled:
        return None
    from .notifiers.email_resend import ResendEmailNotifier

    return ResendEmailNotifier(
        api_key=settings.resend_api_key,
        from_addr=settings.email_from,
        from_name=settings.email_from_name,
        reply_to=settings.email_reply_to,
    )


def _build_sms_notifier(settings: Settings):
    if not settings.sms_enabled:
        return None
    from .notifiers.sms_twilio import TwilioSmsNotifier

    return TwilioSmsNotifier(
        account_sid=settings.twilio_account_sid,
        auth_token=settings.twilio_auth_token,
        from_number=settings.twilio_from_number,
    )


def _send(channel, event, rsvp, ctx, email_notifier, sms_notifier):
    if channel is Channel.EMAIL:
        content = render_email(event, rsvp, ctx)
        return email_notifier.send_email(
            to=rsvp.email, subject=content.subject, text=content.text, html=content.html
        )
    body = render_sms(event, rsvp, ctx)
    return sms_notifier.send_sms(to=rsvp.phone, text=body)


if __name__ == "__main__":
    sys.exit(main())
