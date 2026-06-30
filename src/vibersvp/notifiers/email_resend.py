"""Email notifier backed by Resend.

Swapping providers (e.g. to SMTP or SendGrid) means writing another class with the
same ``send_email`` signature — nothing else in the worker changes.
"""

from __future__ import annotations

import resend

from .base import SendResult


class ResendEmailNotifier:
    def __init__(
        self,
        api_key: str,
        from_addr: str,
        from_name: str,
        reply_to: str | None = None,
    ):
        resend.api_key = api_key
        self._from = f"{from_name} <{from_addr}>"
        self._reply_to = reply_to

    def send_email(self, *, to: str, subject: str, text: str, html: str) -> SendResult:
        params: dict = {
            "from": self._from,
            "to": [to],
            "subject": subject,
            "text": text,
            "html": html,
        }
        if self._reply_to:
            params["reply_to"] = self._reply_to
        try:
            resp = resend.Emails.send(params)
            message_id = resp.get("id") if isinstance(resp, dict) else getattr(resp, "id", None)
            return SendResult.sent(message_id)
        except Exception as exc:  # noqa: BLE001 — record any provider error, keep the run going
            return SendResult.failed(str(exc))
