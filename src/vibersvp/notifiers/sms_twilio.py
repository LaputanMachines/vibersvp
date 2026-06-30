"""SMS notifier backed by Twilio.

Requires a Canada-capable Twilio number that has cleared toll-free verification or
A2P 10DLC registration; until then leave the Twilio env vars blank and SMS is skipped.
"""

from __future__ import annotations

from twilio.rest import Client

from .base import SendResult


class TwilioSmsNotifier:
    def __init__(self, account_sid: str, auth_token: str, from_number: str):
        self._client = Client(account_sid, auth_token)
        self._from = from_number

    def send_sms(self, *, to: str, text: str) -> SendResult:
        try:
            msg = self._client.messages.create(to=to, from_=self._from, body=text)
            return SendResult.sent(msg.sid)
        except Exception as exc:  # noqa: BLE001 — record any provider error, keep the run going
            return SendResult.failed(str(exc))
