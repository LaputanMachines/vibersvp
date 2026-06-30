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
| `Capacity` | Number | optional |
| `Status` | Single select | `Draft`, `Open`, `Full`, `Cancelled`, `Completed` — reminders only fire for `Open`/`Full` |
| `Reminder offsets` | Single line text | optional override, e.g. `24h,2h`; blank = use the default |
| `Notes` | Long text | optional; included in the reminder |

### `RSVPs` (this is the form's table)
| Field | Type | Notes |
|---|---|---|
| `Name` | Single line text | |
| `Email` | Email | |
| `Phone` | Phone number | E.164 ideally, e.g. `+12505550123` |
| `Event` | Link to `Events` | |
| `Status` | Single select | `Going`, `Cancelled`, `Waitlist` — only `Going` gets reminders |
| `Created` | Created time | optional |

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
- **Jack's dashboard** — build an **Interface** grouped by `Event` showing RSVP count vs Capacity
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
     `EMAIL_REPLY_TO`, and (later) `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER`.
   - **Variables:** `CAMPAIGN_NAME`, `CAMPAIGN_CONTACT`, `TIMEZONE`, `DEFAULT_REMINDER_OFFSETS`,
     `EMAIL_FROM_NAME`.
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
- A volunteer is reminded on every channel they have contact info for (email and/or phone);
  SMS is held outside local quiet hours (default 9 AM–9 PM).
