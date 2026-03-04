---
phase: 18-manual-uat-and-bug-fixes
plan: 03
subsystem: testing
tags: [communication, scheduler, apscheduler, smtp, airbnb, vrbo, httpx, fixtures]

# Dependency graph
requires:
  - phase: 14-guest-communication-system
    provides: messenger.py, scheduler.py, emailer.py — the communication flows being verified
  - phase: 16-pdf-form-and-compliance-automation
    provides: ingestion pipeline that triggers communication log creation
provides:
  - Guest communication verification script (COMM-01 through COMM-04)
  - Future-dated Airbnb and VRBO test CSV fixtures
  - Human UAT verification of all four communication flows
affects:
  - 19-operator-ui (communication log display confirmed working)
  - 20-v1.2-release (UAT sign-off required before release)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Verification script pattern: httpx sync client against live API, per-COMM pass/fail tracking"
    - "Future-dated fixture pattern: check-in 30+ days out ensures pre-arrival send time always in future"

key-files:
  created:
    - scripts/verify_guest_comms.py
    - tests/fixtures/airbnb_future.csv
    - tests/fixtures/vrbo_future.csv
  modified: []

key-decisions:
  - "Airbnb fixture uses listing name 'Jay 2BR RV near Sanibel Island & Fort Myers Beach' (must match listing_slug_map)"
  - "VRBO fixture uses 'CHANGE_ME_VRBO_PROPERTY_ID' as Property ID (matches config placeholder)"
  - "Check-in date 2026-04-03 (30 days from execution) ensures pre-arrival send time 2026-04-01 14:00 UTC is always future"
  - "COMM-02 records WARN (not FAIL) when SMTP unconfigured — operator notification email is optional for initial verification"

patterns-established:
  - "UAT script pattern: upload fixture, sleep for background tasks, query logs API, assert specific fields"

# Metrics
duration: 3min
completed: 2026-03-04
---

# Phase 18 Plan 03: Guest Communication UAT Summary

**httpx-based verification script covering COMM-01 to COMM-04 with future-dated Airbnb/VRBO fixtures for pre-arrival scheduling UAT**

## Performance

- **Duration:** ~3 min
- **Started:** 2026-03-04T05:37:10Z
- **Completed:** 2026-03-04T05:39:34Z
- **Tasks:** 1/1 auto tasks complete + human checkpoint verified
- **Files modified:** 3

## Accomplishments
- Created `scripts/verify_guest_comms.py` (551 lines) covering all 4 COMM requirements with clear PASS/FAIL output
- Created `tests/fixtures/airbnb_future.csv` with booking HMUATTEST001 (check-in 2026-04-03, Jay property, "Jay 2BR RV near Sanibel Island & Fort Myers Beach" listing)
- Created `tests/fixtures/vrbo_future.csv` with booking VRBO-UAT-001 (check-in 2026-04-03, CHANGE_ME_VRBO_PROPERTY_ID)
- Script handles async background task timing (5-second sleep after VRBO upload before checking logs)
- Script pauses for COMM-04 restart verification with `input()` prompt before continuing

## Task Commits

Each task was committed atomically:

1. **Task 1: Create future-dated test CSV fixtures and verification script** - `b39331f` (feat)

**Plan metadata:** TBD (docs commit pending)

## Files Created/Modified
- `scripts/verify_guest_comms.py` - COMM-01 through COMM-04 verification script using httpx sync client
- `tests/fixtures/airbnb_future.csv` - Airbnb UAT fixture with check-in 2026-04-03 (HMUATTEST001)
- `tests/fixtures/vrbo_future.csv` - VRBO UAT fixture with check-in 2026-04-03 (VRBO-UAT-001)

## Decisions Made
- VRBO fixture uses `CHANGE_ME_VRBO_PROPERTY_ID` as the Property ID value because that is the actual placeholder in `config/jay.yaml` and `config/minnie.yaml`. The `listing_slug_map` keys must match exactly. This means the VRBO import will only succeed if the operator has not changed these placeholders, or if the operator updates the fixture to match their real configured VRBO Property IDs.
- COMM-02 uses `record_warn` (not `record_fail`) when `operator_notified_at` is null but rendered_message is present, since SMTP may not be configured during initial verification.

## Deviations from Plan
None - plan executed exactly as written.

## Issues Encountered
- xmax-based INSERT detection unreliable with psycopg3 + SQLAlchemy 2.0 (fixed in normalizer.py, commit 70fc4b1)
- SMTP not configured initially (resolved with Mailtrap setup)

## Human Verification Results
All 4 COMM checks passed:
- **COMM-01:** PASS — Airbnb welcome creates `native_configured` log
- **COMM-02:** PASS — VRBO welcome email sent via Mailtrap, `operator_notified_at` set
- **COMM-03:** PASS — Pre-arrival scheduled at 14:00 UTC, check-in - 2 days
- **COMM-04:** PASS — `rebuilt_count=2` after container restart

---
*Phase: 18-manual-uat-and-bug-fixes*
*Completed: 2026-03-04*
