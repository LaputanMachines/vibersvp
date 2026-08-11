<p align="center">
  <img src="assets/banner.png" alt="vibersvp — RSVP + reminders for canvassing volunteer shifts" width="820">
</p>

# vibersvp

RSVP + reminder tool for canvassing volunteer shifts on the **Jack Sandor for Victoria** campaign.

**Airtable** is the database, the public RSVP form, and the candidate's dashboard.
This repo is a small **Python worker** that does the one thing Airtable can't: send timed,
de-duplicated **email + SMS** reminders. It runs entirely on **GitHub Actions** — nothing is
self-hosted.

```
Volunteer ─→ Airtable RSVP form ─┐
                                 ├─→ Airtable base ─┐
Jack ──────→ Airtable dashboard ─┘   Events         │ read every run
                                     RSVPs          │
                                     ReminderLog ←──┤ writes: log rows,
                                                    │ Status → Completed
GitHub Actions cron ─→ python -m vibersvp.run ──────┘
                                 │
                                 ├─→ Resend ─→ volunteer email
                                 └─→ Twilio ─→ volunteer SMS
                                            └─→ Jack's phone (new RSVP, pre-shift roster)
```

Jump to [**How it works**](#how-it-works) for a step-by-step walkthrough of a single run.

---

## 1. Set up the Airtable base

Create a base (any name) with three tables. Field names must match exactly.

### `Events`
| Field | Type | Notes |
|---|---|---|
| `Name` | Single line text | e.g. "Fernwood door-knock" |
| `Start` | Date **with time** | the shift start; set a sensible time zone |
| `End` | Date with time | optional |
| `Location` | Single line text | |
| `Status` | Single select | `Draft`, `Open`, `Cancelled`, `Completed` — reminders only fire for `Open`; the worker auto-sets `Completed` once an event is over |
| `Reminder offsets` | Single line text | optional override, e.g. `24h,2h:sms`; blank = use the default. Add `:email`/`:sms` to pin an offset to one channel |
| `Notes` | Long text | optional; included in the reminder |

### `RSVPs` (this is the form's table)
| Field | Type | Notes |
|---|---|---|
| `Name` | Single line text | |
| `Email` | Email | |
| `Phone` | Phone number | E.164 ideally, e.g. `+12505550123` |
| `Event` | Link to `Events` | |
| `Status` | Single select | `Going`, `Not Going` — only `Going` gets reminders |
| `Created` | Created time | required for **new-RSVP alerts** (below); otherwise optional |

### `ReminderLog` (written by the worker — don't edit by hand)
| Field | Type |
|---|---|
| `Key` | Single line text |
| `RSVP` | Link to `RSVPs` |
| `Event` | Link to `Events` |
| `Offset` | Single line text |
| `Channel` | Single select (`Email`, `SMS`) |
| `Sent at` | Date with time |
| `Status` | Single select (`Sent`, `Failed`) |
| `Provider message id` | Single line text |
| `Error` | Long text |

### The two front-ends (no code)
- **RSVP form** — on the `RSVPs` table, create a **Form** view exposing Name, Email, Phone,
  and Event (add CASL wording: who it's from + how to opt out / "reply STOP").
  Share the public form link with volunteers.
- **Jack's dashboard** — build an **Interface** grouped by `Event` showing the RSVP count
  and the roster. Share a **read-only** link with Jack.

Create a **Personal Access Token** (Airtable → Builder hub → Personal access tokens) with
`data.records:read`, `data.records:write`, and `schema.bases:read` scoped to this base. Grab the
base ID (`app…`) from the API docs for your base.

---

## 2. Configure

Copy `.env.example` → `.env` and fill it in. See that file for every variable.
At minimum you need the Airtable token + base ID and the Resend keys. **Leave the Twilio vars
blank** until your number is verified — SMS is simply skipped, email still works.

---

## 3. Deploy on GitHub Actions (no hosting)

The workflow is `.github/workflows/reminders.yml` — runs `python -m vibersvp.run --once` every
15 minutes.

1. Push this repo to GitHub.
2. **Cost:** a **public** repo gets unlimited free Actions minutes (recommended — no secrets live
   in the code). If you keep it **private**, change the cron to `*/30 * * * *` to stay within the
   free monthly minutes.
3. In **Settings → Secrets and variables → Actions**, add:
   - **Secrets:** `AIRTABLE_API_TOKEN`, `AIRTABLE_BASE_ID`, `RESEND_API_KEY`, `EMAIL_FROM`,
     `EMAIL_REPLY_TO`, and (later) `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER`,
     `JACK_PHONE` (for the new-RSVP alerts and roster digest — see below).
   - **Variables:** `CAMPAIGN_NAME`, `CAMPAIGN_CONTACT`, `TIMEZONE`, `DEFAULT_REMINDER_OFFSETS`,
     `EMAIL_FROM_NAME`, `NEW_RSVP_LOOKBACK` (optional; defaults to `24h`),
     `ROSTER_DIGEST_OFFSET` (optional; defaults to `3h`, `off` to disable).
4. Trigger a manual run from the **Actions** tab (`workflow_dispatch`) to test, then let the
   schedule take over.

> **`*/15` is what we ask for, not what we get.** Measured over 300 consecutive runs, GitHub
> actually fires this job every **~45–70 min**, and stops for **2–6 h overnight**. Scheduled
> workflows are best-effort and queue behind other load, so a coarser cron only makes it worse.
> Every send window is therefore sized to absorb that, and a "3h before" text realistically
> lands 1.8–3h before. Precise delivery would need a hosted scheduler or provider-side
> scheduled sends; we're deliberately not doing that.

### Email (Resend)
Create a Resend account and **verify your sending domain** (add the DNS records) so reminders land
in inboxes. Set `EMAIL_FROM` to an address on that domain.

### SMS (Twilio) — enable later
Sending SMS to Canadian numbers requires a Twilio number that has passed **toll-free verification**
or **A2P 10DLC** registration (needs the campaign's Canadian Business Number; review takes
days–weeks). Until then, keep the Twilio vars unset and run email-only. When approved, add the
three Twilio secrets — no code change needed.

### New-RSVP alerts (text Jack when someone signs up)
When a volunteer RSVPs **`Going`**, the worker texts the organizer once. Set the `JACK_PHONE`
secret to the cell to notify (E.164, e.g. `+12505550123`). Requires Twilio to be configured (the
three vars above) — without it, the alert is skipped just like reminders.

- **Exactly once per RSVP.** The alert reuses the `ReminderLog` idempotency: it writes a row with
  `Offset = new-rsvp`, `Channel = SMS`, so re-running the cron never re-texts.
- **First-deploy guard.** Only RSVPs whose `Created` time is within `NEW_RSVP_LOOKBACK` (default
  `24h`) count as "new", so turning this on doesn't blast the organizer about your existing RSVP
  back-catalogue. This is why the `Created` field on the `RSVPs` table is **required** for this
  feature — RSVPs with no `Created` value are skipped.
- **No quiet hours.** Unlike volunteer reminders, these operational alerts to the organizer's own
  number send immediately, day or night.

To disable, leave `JACK_PHONE` unset.

### Pre-shift roster digest (text Jack the list before a canvass)
A few hours before each `Open` event, the worker texts `JACK_PHONE` the roster for that shift:

```
Jack Sandor for Victoria: Canvass in ~3h - Fernwood door-knock, Wednesday, July 1 at
11:00 AM PDT, 1234 Gladstone Ave. 3 going: Alex Chen, Pat Volunteer, Sam Ng.
```

- **Lead time** is `ROSTER_DIGEST_OFFSET` (default `3h`, same `m`/`h`/`d` syntax). It's a
  single campaign-wide value on purpose — a per-event `Reminder offsets` override changes the
  *volunteers'* schedule, not Jack's heads-up. Set the variable to **`off`** to disable;
  blank means "use the default", so an Actions variable you never created can't silently
  switch it off.
- **Same window rule as reminders** (`start − offset ≤ now < start`), so cron drift makes the
  digest later rather than earlier, and it never lands after the shift has started.
- **The offset is also the drift budget.** GitHub's scheduled cron asks for every 15 min but
  delivers every ~45–70 min, with multi-hour stalls overnight. A window that happens to
  contain no run drops that digest for good, because the window closes at the shift's start
  and nothing retries it. Measured over 300 runs and 21 events, a `2h` window missed 3 of
  them and gave a median of 1.4h notice; `3h` misses 1 and gives a median of 2.6h. Widening
  past `3h` buys no more coverage — it only makes the roster staler. Shrinking it drops more.
  Guaranteed on-the-minute delivery would need scheduled sends (Twilio `SendAt`) instead of
  polling; that's not built.
- **Exactly once per (event, lead time)**, via a `ReminderLog` row with `Offset = roster-3h`.
  That row links the `Event` but no `RSVP` — it's about the whole shift.
- **Empty rosters still send** ("No RSVPs yet") — that's the text most worth getting.
- **Names only**, capped at 12 with a `(+N more)` tail so a big shift doesn't turn into a
  five-segment SMS. The full roster is on the dashboard.
- **No quiet hours**, same as the new-RSVP alerts — a 3h digest for a 9 AM canvass would
  otherwise be held until 9 AM and never send.
- Needs Twilio configured and `JACK_PHONE` set, exactly like the new-RSVP alerts.

---

## 4. Local development & testing

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Offline unit tests (no network, no Airtable):
pytest

# Dry run against your real base — logs what WOULD send, sends nothing, writes no log rows:
python -m vibersvp.run --once --dry-run

# Override the clock to test a specific moment:
python -m vibersvp.run --once --dry-run --now 2026-07-01T17:00:00Z
```

**End-to-end smoke test:** create a test event ~2h and ~24h out, RSVP yourself (your own email/phone),
run without `--dry-run`, confirm you receive the messages and that `ReminderLog`
rows appear — then run again and confirm **nothing re-sends**.

---

## How it works

### The shape of the code

The worker is stateless. It holds no queue and no cursor — every run re-reads the whole base,
recomputes what should have happened by `now`, and uses `ReminderLog` as the only memory of what
it already did. That's what makes an unreliable cron survivable.

| Module | I/O? | Job |
|---|---|---|
| `models.py` | pure | Plain dataclasses (`Event`, `Rsvp`, `Offset`, …) and the **idempotency key** functions |
| `scheduler.py` | pure | All the decisions: which reminders/digests/alerts are due, which events are over. Takes `now` as an argument and never reads the clock |
| `templates.py` | pure | Renders the email and SMS bodies |
| `config.py` | env | `Settings` — env vars and `.env`, with the blank-value guards |
| `airtable.py` | network | The only place `pyairtable` appears. Maps records ⇄ models |
| `notifiers/` | network | `ResendEmailNotifier`, `TwilioSmsNotifier` |
| `run.py` | — | Orchestrates the above in the order below |

The pure/impure split is the reason `pytest` needs no network, no Airtable, and no env: the three
pure modules are where the logic lives, and they're deterministic given `now`.

### One run, step by step

```
python -m vibersvp.run --once
  │
  ├─ Settings()                     config.py — env + .env; hard-fails if the Airtable vars are missing
  ├─ now = _parse_now(--now)        the single clock read; everything below is a pure function of it
  ├─ repo.load_events()             READ  Events, every row
  ├─ repo.load_rsvps()              READ  RSVPs; one Rsvp per linked Event, so a 3-shift signup
  │                                       becomes 3 Rsvps sharing one record id
  ├─ compute_due_reminders()        decide: which volunteer reminders are in window
  ├─ events_to_complete()           decide: which Open events are over
  ├─ log the summary line           see "Reading the log" below
  ├─ _complete_finished_events()    WRITE Status → Completed. Runs first and never blocks sends;
  │                                       a failure here is logged and the run continues
  │
  ├─ early exit if nothing could possibly send
  │    (no due reminders AND both organizer features disabled)
  │
  ├─ repo.load_sent_keys()          READ  ReminderLog once → the set of keys with Status = Sent
  │
  ├─ compute_new_rsvp_alerts()  → _alert_new_rsvps()       SMS to JACK_PHONE, quiet hours ignored
  ├─ compute_roster_digests()   → _send_roster_digests()   SMS to JACK_PHONE, quiet hours ignored
  │
  └─ for each due reminder:
       key already in sent_keys?    → skip           (counts as dup)
       channel not configured?      → skip           (unconfigured)
       SMS outside quiet hours?     → skip this run  (quiet) — a later run in the window retries
       render + send                → templates → Resend / Twilio
       repo.log_reminder()          → WRITE one ReminderLog row, Sent or Failed
```

Organizer texts are sent **before** volunteer reminders, so a quiet-hours deferral or a provider
outage on the volunteer side can't delay Jack's heads-up.

Exit code is `1` if any send failed, `0` otherwise. A red Actions run means a provider rejected
something — not that a reminder was missed. Missed reminders are silent by construction, which is
why the log summary line matters.

### The four things a run can do

| What | Fires when | To whom | Channel | Quiet hours |
|---|---|---|---|---|
| **Volunteer reminder** | `start − offset ≤ now < start`, once per offset in the event's `Reminder offsets` or `DEFAULT_REMINDER_OFFSETS` | every `Going` RSVP on the event | email and/or SMS, per the offset's `:email`/`:sms` suffix | SMS deferred to a later run |
| **New-RSVP alert** | RSVP is `Going` and its `Created` time is within `NEW_RSVP_LOOKBACK` | `JACK_PHONE` | SMS | ignored — sends day or night |
| **Roster digest** | `start − ROSTER_DIGEST_OFFSET ≤ now < start` | `JACK_PHONE` | SMS | ignored |
| **Event completion** | `now ≥ End` (or `Start` if no `End`) and status is `Open` | — | Airtable write only | — |

Only `Open` events are considered — `Draft`, `Cancelled` and already-`Completed` events are left
alone entirely — and only `Going` RSVPs count. A reminder needs at least one attendee; a roster
digest fires even with **zero** ("No RSVPs yet"), because that's the text Jack most needs.

### Channels and quiet hours

An offset decides its own channels. A **bare** offset (`24h`) sends on every channel the volunteer
has contact details for; a **suffixed** one (`2h:sms`) pins to exactly one. So the default
`24h,2h:sms` means: a 24h reminder on email *and* SMS, then a text-only nudge 2h out. The suffix is
stripped from the idempotency key, so adding or removing one never re-sends a reminder that already
went.

Volunteer SMS is held to `SMS_QUIET_START_HOUR`–`SMS_QUIET_END_HOUR` local time (default 9 AM–9 PM,
CRTC-friendly). A text that comes due outside those hours isn't dropped — it's skipped for that run
and picked up by the next run still inside the send window. Email ignores quiet hours, and so do
both organizer texts: Jack opted in to his own number, and deferring a pre-shift roster until 9 AM
would push it past the shift it's about.

### Idempotency: the key scheme

Every outbound message is identified by a stable four-segment key written to `ReminderLog`. Before
sending, the worker checks the key against the keys already logged with `Status = Sent`; after
sending, it writes the key back. Re-running the job is therefore free.

| Message | Key |
|---|---|
| Volunteer reminder | `<rsvp id>::<event id>::<offset>::<Email\|SMS>` |
| New-RSVP alert | `<rsvp id>::<event id>::new-rsvp::SMS` |
| Roster digest | `roster::<event id>::roster-<offset>::SMS` |

The placeholder segments (`roster` where an RSVP id would go, `no-event` for an RSVP whose event
link is missing) keep every key well-formed and four-wide. Airtable record ids always start with
`rec`, so a placeholder can never collide with a real one — and the `roster-` prefix on the offset
is what stops a `roster-3h` digest colliding with a volunteer's own `3h` reminder for the same event.

Two consequences worth knowing:

- **A `Failed` row is retried.** Only `Sent` rows dedupe, so a provider error one run is picked up
  by the next — as long as the send window is still open.
- **A `Sent` row is final.** There's no expiry or re-send. Deleting the row by hand is the only way
  to make a message go out twice, which is why `ReminderLog` says don't edit it.

### Reading the log

Every run opens with a single line that answers "is this thing configured correctly" (wrapped here
for width):

```
now=2026-08-11T21:57:24+00:00 | events=42 rsvps=12 due=0 complete=0 |
  email=True sms=True rsvp_alerts=True roster_digest=3h dry_run=True
```

`email`/`sms`/`rsvp_alerts` are `False` and `roster_digest` is `False` when the relevant config is
missing — that's the fastest way to spot a feature that's silently off. It closes with a counts
dict (`sent`, `dup`, `quiet`, `unconfigured`, `failed`, `alerted`, `digested`, …).

### How it goes quiet

The failure mode of this design isn't a crash, it's silence. Both known instances are guarded now,
but they're the shape of thing to look for:

- **A blank env var is not an unset one.** The workflow passes every tunable as
  `${{ vars.X }}`, so an Actions variable that was never created arrives as `""` — which
  *overrides* the field default instead of falling back to it. For `DEFAULT_REMINDER_OFFSETS` that
  meant an empty offset list and therefore zero volunteer reminders, with no error and `due=0` on
  every run. `config.py` now guards `TIMEZONE`, `ROSTER_DIGEST_OFFSET` and
  `DEFAULT_REMINDER_OFFSETS`; `tests/test_config.py` covers all of them. Add a guard whenever you
  add a variable.
- **A send window can close unused.** Reminder and digest windows both end at the event's start,
  and nothing retries afterwards. If the cron happens not to fire inside a window, that message is
  gone for good. The 24h reminder has a 24-hour window and is effectively safe; the short ones are
  not, which is why `ROSTER_DIGEST_OFFSET` is sized as a drift budget rather than a preference.
