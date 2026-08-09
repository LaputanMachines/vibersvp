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
Volunteer → Airtable RSVP form ─┐
                                ├→ Airtable base (Events, RSVPs, ReminderLog)
Jack → Airtable dashboard ──────┘            ▲
                                             │ reads/writes
GitHub Actions cron (every 15m) → python -m vibersvp.run → Resend (email) + Twilio (SMS)
```

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
     `ROSTER_DIGEST_OFFSET` (optional; defaults to `2h`, `off` to disable).
4. Trigger a manual run from the **Actions** tab (`workflow_dispatch`) to test, then let the
   schedule take over.

> GitHub cron drifts 5–30 min, so a "2h before" reminder may land ~1–2h before the event. That's
> fine for a canvass nudge and the only way to be more precise is to host a scheduler, which we're
> deliberately not doing.

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
Two hours before each `Open` event, the worker texts `JACK_PHONE` the roster for that shift:

```
Jack Sandor for Victoria: Canvass in ~2h - Fernwood door-knock, Wednesday, July 1 at
11:00 AM PDT, 1234 Gladstone Ave. 3 going: Alex Chen, Pat Volunteer, Sam Ng.
```

- **Lead time** is `ROSTER_DIGEST_OFFSET` (default `2h`, same `m`/`h`/`d` syntax). It's a
  single campaign-wide value on purpose — a per-event `Reminder offsets` override changes the
  *volunteers'* schedule, not Jack's heads-up. Set the variable to **`off`** to disable;
  blank means "use the default", so an Actions variable you never created can't silently
  switch it off.
- **Same window rule as reminders** (`start − offset ≤ now < start`), so cron drift just makes
  the digest a bit later, never after the shift has started.
- **Exactly once per (event, lead time)**, via a `ReminderLog` row with `Offset = roster-2h`.
  That row links the `Event` but no `RSVP` — it's about the whole shift.
- **Empty rosters still send** ("No RSVPs yet") — that's the text most worth getting.
- **Names only**, capped at 12 with a `(+N more)` tail so a big shift doesn't turn into a
  five-segment SMS. The full roster is on the dashboard.
- **No quiet hours**, same as the new-RSVP alerts — a 2h digest for a 9 AM canvass would
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

## How it works (the safety model)

- `scheduler.compute_due_reminders` is **pure**: given events, RSVPs, and `now`, it returns the
  reminders whose send window (`start − offset ≤ now < start`) is open.
- Each reminder has a stable **key** (`rsvp::offset::channel`). Before sending, the worker checks
  the key against `ReminderLog`; after sending it writes the key back. So the job is **idempotent** —
  safe to run every 15 minutes and resilient to cron drift or a missed run.
- Each offset picks its own channels: a bare offset (`24h`) reminds on every channel the
  volunteer has contact info for, while a suffixed one (`2h:sms`) pins to one. The default
  `24h,2h:sms` sends the 24h reminder on email + SMS and the 2h nudge as text only.
- SMS is held outside local quiet hours (default 9 AM–9 PM); a deferred text is picked up by a
  later run still inside the send window.
- When someone RSVPs `Going`, the organizer gets a one-time text (`JACK_PHONE`), deduped through
  the same `ReminderLog` key mechanism and scoped to recent RSVPs by `NEW_RSVP_LOOKBACK`.
- `ROSTER_DIGEST_OFFSET` before each shift, the organizer gets one more text listing who's
  coming — keyed `roster::<event id>::roster-<offset>::SMS`, so it's one digest per event, ever.
- After an event is over, the worker flips its `Status` from `Open` to `Completed` (using `End`
  if set, otherwise `Start`), so the dashboard reflects what's done. `Draft`, `Cancelled`, and
  already-`Completed` events are left untouched.
