"""Render reminder messages. Pure — all context is passed in, nothing is read here.

CASL/CRTC note: these are reminders for an event the volunteer actively signed up for,
but we still identify the sender and give an opt-out in every message.
"""

from __future__ import annotations

from dataclasses import dataclass
from zoneinfo import ZoneInfo

from .models import Event, Rsvp


@dataclass(frozen=True)
class EmailContent:
    subject: str
    text: str
    html: str


@dataclass(frozen=True)
class MessageContext:
    campaign_name: str
    campaign_contact: str
    tz: ZoneInfo


def _format_when(event: Event, tz: ZoneInfo) -> str:
    """e.g. 'Wednesday, July 1 at 6:00 PM PDT' in the campaign's local time zone."""
    if event.start is None:
        return "TBD"
    local = event.start.astimezone(tz)
    # %-d / %-I are platform-specific; strip leading zeros manually for portability.
    day = local.strftime("%A, %B %d").replace(" 0", " ")
    time = local.strftime("%I:%M %p %Z").lstrip("0")
    return f"{day} at {time}"


def _first_name(name: str) -> str:
    return (name or "there").strip().split(" ")[0] or "there"


def render_email(event: Event, rsvp: Rsvp, ctx: MessageContext) -> EmailContent:
    when = _format_when(event, ctx.tz)
    where = event.location or "see details in the event"
    subject = f"Reminder: {event.name} — {when}"

    text = (
        f"Hi {_first_name(rsvp.name)},\n\n"
        f"This is a reminder that you signed up to canvass with the "
        f"{ctx.campaign_name} campaign:\n\n"
        f"  Event:    {event.name}\n"
        f"  When:     {when}\n"
        f"  Where:    {where}\n\n"
        f"{('Notes: ' + event.notes) if event.notes else ''}"
        f"{chr(10) if event.notes else ''}"
        f"Thanks for volunteering — see you there!\n\n"
        f"— {ctx.campaign_name}\n\n"
        f"You're receiving this because you RSVP'd to this event. "
        f"To stop reminders, reply to this email or contact {ctx.campaign_contact}."
    )

    notes_html = f"<p><strong>Notes:</strong> {event.notes}</p>" if event.notes else ""
    html = (
        f"<p>Hi {_first_name(rsvp.name)},</p>"
        f"<p>This is a reminder that you signed up to canvass with the "
        f"<strong>{ctx.campaign_name}</strong> campaign:</p>"
        f"<ul>"
        f"<li><strong>Event:</strong> {event.name}</li>"
        f"<li><strong>When:</strong> {when}</li>"
        f"<li><strong>Where:</strong> {where}</li>"
        f"</ul>"
        f"{notes_html}"
        f"<p>Thanks for volunteering — see you there!</p>"
        f"<p>— {ctx.campaign_name}</p>"
        f"<hr>"
        f"<p style='font-size:12px;color:#666'>You're receiving this because you RSVP'd "
        f"to this event. To stop reminders, reply to this email or contact "
        f"{ctx.campaign_contact}.</p>"
    )
    return EmailContent(subject=subject, text=text, html=html)


def render_sms(event: Event, rsvp: Rsvp, ctx: MessageContext) -> str:
    when = _format_when(event, ctx.tz)
    where = event.location or "see email for details"
    return (
        f"{ctx.campaign_name}: Reminder — you're canvassing at {event.name}, "
        f"{when}, {where}. Reply STOP to opt out."
    )
