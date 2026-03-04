---
phase: 18-manual-uat-and-bug-fixes
verified: 2026-03-04T18:44:04Z
status: passed
score: 7/7 must-haves verified
gaps: []
---

# Phase 18: Manual UAT & Bug Fixes Verification Report

**Phase Goal:** Every automation flow (PDF fill, PDF email, welcome message, pre-arrival message) runs correctly in the live application -- verified by a human triggering each flow
**Verified:** 2026-03-04T18:44:04Z
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| #  | Truth                                                                                               | Status     | Evidence                                                                                                                                                |
|----|-----------------------------------------------------------------------------------------------------|------------|---------------------------------------------------------------------------------------------------------------------------------------------------------|
| 1  | A filled PDF shows all guest and booking fields visibly populated in macOS Preview                  | VERIFIED   | `pdf_filler.py` overrides `/DA` from ArialMT CIDFont to `/Helv`, calls `auto_regenerate=True`, sets `/Ff=1` (read-only). Operator confirmed in SUMMARY. |
| 2  | SMTP email flow sends filled PDF to resort contact (verified in preview mode)                       | VERIFIED   | `submission.py` full pipeline: fill PDF → format email → `send_with_retry()`. Operator confirmed email in Mailtrap with `booking_form.pdf` attached.    |
| 3  | Preview mode holds first N submissions; subsequent submissions auto-send                            | VERIFIED   | `should_auto_submit()` counts `status in ('submitted', 'confirmed')`. Threshold logic correct after bug fix. Operator walked lifecycle via script.       |
| 4  | Airbnb booking triggers welcome message with `native_configured` status logged                      | VERIFIED   | `normalizer._create_communication_logs()` creates `CommunicationLog(status="native_configured")` for Airbnb. COMM-01 PASS confirmed in SUMMARY.         |
| 5  | VRBO/RVshare booking triggers operator notification email with rendered welcome text for copy-paste | VERIFIED   | `messenger.prepare_welcome_message()` renders template, sends operator notification, sets `operator_notified_at`. COMM-02 PASS confirmed in SUMMARY.     |
| 6  | Booking with check-in 2+ days away creates a scheduled pre-arrival job with correct timing         | VERIFIED   | `scheduler.schedule_pre_arrival_job()` fires at `check_in - 2 days, 14:00 UTC`. COMM-03 PASS confirmed in SUMMARY.                                     |
| 7  | After app restart, previously scheduled pre-arrival jobs are rebuilt and still fire                 | VERIFIED   | `rebuild_pre_arrival_jobs()` called in `lifespan()` on startup; re-registers all pending jobs from DB. COMM-04 `rebuilt_count=2` confirmed in SUMMARY.  |

**Score:** 7/7 truths verified

### Required Artifacts

| Artifact                                  | Expected                                               | Status     | Details                                                                 |
|-------------------------------------------|--------------------------------------------------------|------------|-------------------------------------------------------------------------|
| `app/compliance/pdf_filler.py`            | Helvetica override + auto_regenerate + read-only fill  | VERIFIED   | 238 lines. `/DA` override loop, `auto_regenerate=True`, `/Ff=1` loop. No stubs. |
| `app/compliance/submission.py`            | Preview mode threshold counting sent submissions       | VERIFIED   | 263 lines. `should_auto_submit()` counts `status in ('submitted', 'confirmed')`. |
| `app/ingestion/normalizer.py`             | Pre-check INSERT detection (not xmax) for booking upsert | VERIFIED | 631 lines. `existing_booking_ids` set built before upsert loop at line 337. xmax comment at 335 confirms intent. |
| `scripts/verify_pdf_fill.py`              | PDF fill verification script for PDFC-01               | VERIFIED   | 108 lines. Fills production template, reads back field values, opens Preview. |
| `scripts/verify_email_submission.py`      | Email submission + preview mode verification script    | VERIFIED   | 395 lines. Full lifecycle: preview_pending → approve → email → auto-submit. |
| `scripts/verify_guest_comms.py`           | Guest comms verification script (COMM-01 through COMM-04) | VERIFIED | 629 lines. httpx client, unique run IDs, all 4 COMM checks with PASS/FAIL output. |
| `tests/fixtures/airbnb_future.csv`        | Future-dated Airbnb fixture for UAT                    | VERIFIED   | 3 lines. Booking HMUATTEST001, check-in 2026-04-03, "Jay 2BR RV" listing. |
| `tests/fixtures/vrbo_future.csv`          | Future-dated VRBO fixture for UAT                      | VERIFIED   | 3 lines. Booking VRBO-UAT-001, check-in 2026-04-03, CHANGE_ME_VRBO_PROPERTY_ID. |
| `app/communication/scheduler.py`          | APScheduler pre-arrival job scheduling + rebuild       | VERIFIED   | 166 lines. `schedule_pre_arrival_job()` + `rebuild_pre_arrival_jobs()`. |
| `app/communication/messenger.py`          | Guest message rendering + operator notification        | VERIFIED   | 382 lines. `prepare_welcome_message()`, `render_guest_message()`, `operator_notified_at`. |

### Key Link Verification

| From                                | To                                          | Via                                      | Status     | Details                                                                   |
|-------------------------------------|---------------------------------------------|------------------------------------------|------------|---------------------------------------------------------------------------|
| `pdf_filler.fill_resort_form()`     | PDF output bytes                            | `/DA` override + `auto_regenerate=True` + `/Ff=1` | WIRED | Lines 196-227: `/DA` loop, `update_page_form_field_values`, read-only loop. |
| `submission.process_booking_submission()` | `pdf_filler.fill_resort_form()`        | Direct call at line 169                  | WIRED      | Return value assigned to `filled_pdf_bytes`, passed to `send_with_retry()`. |
| `submission.should_auto_submit()`   | `ResortSubmission.status`                   | `status.in_(('submitted', 'confirmed'))` | WIRED      | Bug fix at line 62: counts sent submissions, not the flag.                |
| `normalizer.ingest_csv()`           | INSERT vs UPDATE detection                  | `existing_booking_ids` pre-check         | WIRED      | Lines 337-379: set built before upsert, compared per-record after.        |
| `normalizer._create_communication_logs()` | Airbnb `native_configured` status   | `if platform == "airbnb"` at line 218    | WIRED      | Creates `CommunicationLog(status="native_configured")` for Airbnb.        |
| `normalizer._create_communication_logs()` | `schedule_pre_arrival_job()`         | Called at line 246 for all platforms     | WIRED      | Passes `booking_id` and `check_in_date` from DB row.                      |
| `scheduler.rebuild_pre_arrival_jobs()` | `app.main.lifespan()`                  | Called at line 126 of `main.py`          | WIRED      | `await rebuild_pre_arrival_jobs()` on startup; `rebuilt_count` logged.    |
| `messenger.prepare_welcome_message()` | `operator_notified_at` field           | `send_operator_notification_with_retry()` | WIRED     | Sets `operator_notified_at = datetime.now(timezone.utc)` at line 198.    |

### Requirements Coverage

| Requirement | Status     | Evidence                                                                      |
|-------------|------------|-------------------------------------------------------------------------------|
| PDFC-01     | SATISFIED  | PDF fill with Helvetica/auto_regenerate verified by operator in macOS Preview |
| PDFC-02     | SATISFIED  | Email with `booking_form.pdf` confirmed in Mailtrap via verify_email_submission.py |
| PDFC-03     | SATISFIED  | Preview mode lifecycle (hold → approve → auto-send) confirmed by operator     |
| COMM-01     | SATISFIED  | Airbnb welcome `native_configured` log confirmed by verify_guest_comms.py     |
| COMM-02     | SATISFIED  | VRBO operator notification email with rendered welcome text confirmed          |
| COMM-03     | SATISFIED  | Pre-arrival job scheduled at `check_in - 2 days, 14:00 UTC` confirmed         |
| COMM-04     | SATISFIED  | `rebuilt_count=2` after container restart confirmed by operator                |

### Anti-Patterns Found

None. All three application files (`pdf_filler.py`, `submission.py`, `normalizer.py`) and all three verification scripts are fully implemented with no TODO, FIXME, placeholder, or empty return patterns.

### Human Verification Required

All human verification was completed by the operator during UAT. Per the prompt: "All human checkpoints were verified and approved by the operator." The 18-03-SUMMARY.md records explicit PASS results for all 4 COMM checks.

### Bugs Fixed During UAT

Three bugs were discovered and fixed during UAT:

1. **PDF CIDFont rendering** (`pdf_filler.py`, commit `14bbe05`): Template used ArialMT CIDFont (/F3) which caused pypdf's `auto_regenerate` to crash. Fixed by overriding `/DA` to `/Helv` (Helvetica) before calling `update_page_form_field_values(auto_regenerate=True)` and setting fields read-only with `/Ff=1`.

2. **Preview mode threshold** (`submission.py`, commit `71da457`): `should_auto_submit()` counted `submitted_automatically=True`, but manual approvals set this flag to `False` (since auto_submit was False at evaluation time), creating a circular dependency where the threshold could never be reached. Fixed to count `status in ('submitted', 'confirmed')`.

3. **INSERT detection** (`normalizer.py`, commit `70fc4b1`): `xmax`-based INSERT vs UPDATE detection was unreliable with psycopg3 + SQLAlchemy 2.0 on PostgreSQL 16. Fixed by querying `existing_booking_ids` as a set before the upsert loop, then comparing per-record after.

All three fixes are confirmed present in the codebase.

---

_Verified: 2026-03-04T18:44:04Z_
_Verifier: Claude (gsd-verifier)_
