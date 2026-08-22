"""Tests for the Resend `from` header composition.

Resend rejects anything that isn't `email@example.com` or `Name <email@example.com>`,
and it rejects it for *every* send — so a malformed header here silences email entirely.
"""

from __future__ import annotations

import sys
import types

import pytest


@pytest.fixture
def notifier_cls(monkeypatch):
    """Import the notifier against a stub `resend` module — no network, no real SDK."""
    stub = types.ModuleType("resend")
    stub.api_key = None
    stub.Emails = types.SimpleNamespace(send=lambda params: {"id": "stub"})
    monkeypatch.setitem(sys.modules, "resend", stub)
    monkeypatch.delitem(sys.modules, "vibersvp.notifiers.email_resend", raising=False)
    from vibersvp.notifiers.email_resend import ResendEmailNotifier

    return ResendEmailNotifier


def test_from_uses_name_and_address(notifier_cls):
    n = notifier_cls(api_key="re_x", from_addr="hello@example.com", from_name="Jack Sandor")
    assert n._from == "Jack Sandor <hello@example.com>"


def test_blank_name_falls_back_to_the_bare_address(notifier_cls):
    # The regression: `f"{name} <{addr}>"` with an empty name yields " <hello@example.com>",
    # which Resend rejects with "Invalid `from` field".
    n = notifier_cls(api_key="re_x", from_addr="hello@example.com", from_name="")
    assert n._from == "hello@example.com"


def test_whitespace_name_falls_back_to_the_bare_address(notifier_cls):
    n = notifier_cls(api_key="re_x", from_addr="hello@example.com", from_name="   ")
    assert n._from == "hello@example.com"


def test_surrounding_whitespace_is_stripped(notifier_cls):
    n = notifier_cls(api_key="re_x", from_addr="  hello@example.com  ", from_name="  Jack  ")
    assert n._from == "Jack <hello@example.com>"
