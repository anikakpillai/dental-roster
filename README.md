# Unity Roster

**AI-drafted, rule-enforced weekly staff scheduling for a dental practice — built on live Open Dental data.**

Unity Roster builds the weekly staff schedule for Unity Dental & Implant Centre. It reads the real appointment book from Open Dental, has Gemini draft a sensible roster around it, then passes that draft through a deterministic validator that enforces every hard rule before a human ever sees it. The practice manager reviews, tweaks, and prints — from one button.

> **AI proposes. Code enforces. Open Dental is truth. Config is policy. The manager has the last word.**

---

## Why it exists

Rostering a clinic by hand means reconciling the appointment book, staff availability, hour caps, and per-dentist assistant needs every single week. Pure-AI scheduling is too unreliable for that (invented shifts, broken hour caps); pure-rules scheduling is too rigid (can't weigh preferences or trade-offs). Unity Roster splits the job:

| Layer | Component | Role |
|---|---|---|
| **Truth** | Open Dental (MariaDB, read-only) | Which dentists actually work, and when — derived from booked appointments |
| **Policy** | YAML config (`config/`) | Who exists, their roles, caps, days off, per-dentist assistant counts |
| **Proposal** | Gemini (`gemini-2.5-flash`) | Drafts the roster: assistants, front desk, staggering, preferences |
| **Law** | Deterministic validator | Enforces every hard rule; corrects or rejects the draft, with retries |
| **Human** | Web UI | Manager reviews warnings, edits cells, adds weekly exceptions, prints |

The design rule that shaped everything: **no layer may silently lie to the one above it.** Every correction the validator makes is surfaced as a named, timestamped warning.

## What the validator guarantees

- **Dentist facts are law.** Dentists appear exactly on the days Open Dental shows booked appointments, spanning first patient to last. A dentist the AI invents is removed; one it omits is inserted; wrong times are corrected. Identical output every build.
- **Coverage remap.** A dentist on leave can have their book folded into a covering dentist (e.g. `covers_provider_ids`) with no double-counting of assistant demand.
- **Hour caps.** Daily and weekly maximums per person; over-cap shifts are trimmed and flagged.
- **Days off & weekly exceptions.** Recurring days off and one-off manager exceptions ("Rajat off Monday", "Erika leaves 2 pm Friday") are enforced for support staff; for dentists, Open Dental wins and conflicts are flagged.
- **Assistant coverage depth.** Each dentist has a required assistant count (default 1; e.g. 2 for Dr Pillai). Any window staffed below that count is flagged with exact times: *"under-covered 17:00–19:00 (0 of 1 assistants)"*. Long dentist days are covered by staggered assistant pairs.
- **Role rules.** Hygienists run their own book and are excluded from the roster; fixed-shift staff (coordinator, sterilization) keep their hours.

## Features

- **One-click weekly build** from live appointment data, with a plain-English summary
- **Weekly exceptions panel** — structured one-off changes (off / starts late / leaves early, with notes), persisted per week, enforced by the validator
- **Free-text manager notes** — soft guidance the AI weighs ("busy Thursday, keep Pari mornings")
- **Named warnings** for every correction or shortfall — nothing is fixed silently
- **Staff management UI** — add, edit, deactivate staff without touching config files
- **Print-ready grid** grouped by role
- **Resilient AI calls** — JSON repair for malformed model output, retries, and backoff for transient API errors

## Tech stack

- **Backend:** Python 3.13, FastAPI, google-genai SDK (`gemini-2.5-flash`, thinking disabled)
- **Frontend:** single-page vanilla JS + HTML (`web/roster.html`)
- **Data:** Open Dental's MariaDB, accessed read-only via a dedicated user
- **Config:** YAML (`staff.yaml`, `rules.yaml`) — read with BOM-tolerant encoding, written UTF-8
- **Hosting:** runs on the practice's Windows server; auto-starts on boot; accessed at `localhost:8000`

## Repository layout

    src/roster/
      db/            queries.py — read-only Open Dental access
      domain/        models.py — staff, appointments, roles
      config/        loader.py, writer.py, schema.py — YAML policy layer
      engine/
        demand.py         appointment demand + dentist day truth
        ai_context.py     briefing assembled for the AI
        ai_roster.py      Gemini call, JSON repair, retries
        validator.py      the law: every hard rule, every correction named
        roster_service.py end-to-end build pipeline
      main.py        FastAPI app + REST API
    web/roster.html  the manager's single-page UI
    config/          staff.yaml, rules.yaml (policy; server copy is canonical)

## Deployment model

Development happens on a Mac; the server only ever pulls:

    Mac (VS Code) --> git push --> GitHub --> git pull on the practice server

The server never pushes. Provider IDs and staffing policy live in the server's config only. After each pull: kill the running process, restart via `start-roster.bat`, hard-refresh the browser.

## Author

Built by **Anika Pillai** for Unity Dental & Implant Centre — an exercise in making AI scheduling trustworthy enough for real operations: not by trusting the model, but by wrapping it in verifiable law.
