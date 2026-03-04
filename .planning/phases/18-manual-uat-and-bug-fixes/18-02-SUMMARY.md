---
phase: 18-manual-uat-and-bug-fixes
plan: 02
subsystem: compliance
tags: [email, smtp, mailtrap, preview-mode, auto-submit, pdf-attachment]

requires:
  - phase: 16-pdf-form-and-compliance-automation
    provides: submission.py, emailer.py, compliance API routes
  - plan: 18-01
    provides: verified PDF fill (correct rendering)
provides:
  - Email submission verification script (PDFC-02, PDFC-03)
  - Fixed preview mode threshold logic
  - Verified end-to-end email delivery with PDF attachment
affects:
  - 20-v1.2-release (UAT sign-off for compliance automation)

tech-stack:
  added: []
  patterns:
    - "Preview mode threshold: count status='submitted'/'confirmed' (not submitted_automatically flag)"

key-files:
  created:
    - scripts/verify_email_submission.py
  modified:
    - app/compliance/submission.py
    - app/ingestion/normalizer.py

key-decisions:
  - "Preview mode threshold counts successful sends (status in submitted/confirmed) not submitted_automatically flag"
  - "INSERT detection uses pre-check approach instead of xmax (unreliable with psycopg3 + SQLAlchemy 2.0)"

completed: 2026-03-04
---

# Phase 18 Plan 02: Email Submission & Preview Mode (PDFC-02/PDFC-03) Summary

**Verified end-to-end email submission with PDF attachment and preview mode gating lifecycle**

## Performance

- **Tasks:** 1/1 auto task complete + human checkpoint verified
- **Files modified:** 3 (1 created, 2 modified)
- **Bug fixes:** 2 (preview mode threshold, INSERT detection)

## Accomplishments
- Created `scripts/verify_email_submission.py` (395 lines) — interactive walkthrough of preview mode lifecycle
- Fixed preview mode threshold: was counting `submitted_automatically=True` (circular dependency), now counts successful sends
- Fixed normalizer INSERT detection: replaced unreliable xmax approach with pre-check for psycopg3 compatibility
- Human-verified: emails arrive in Mailtrap with booking_form.pdf attached, correct subject line
- Human-verified: preview mode holds first submissions, auto-submits after threshold reached

## Task Commits

1. **Task 1: Create email submission verification script** — `faebd22` (feat)
2. **Bug fix: Preview mode threshold** — `71da457` (fix)
3. **Bug fix: INSERT detection** — `70fc4b1` (fix)

## Bugs Fixed

### 1. Preview Mode Threshold (Circular Dependency)
`should_auto_submit()` counted `submitted_automatically=True`, but approvals set it to `False` (since auto_submit was `False` at evaluation time). Threshold could never be reached. Fixed to count `status in ('submitted', 'confirmed')`.

### 2. Normalizer INSERT Detection (psycopg3 + xmax)
The `xmax`-based INSERT vs UPDATE detection was unreliable with psycopg3 + SQLAlchemy 2.0 on PostgreSQL 16. Replaced with pre-check: query existing booking IDs before the upsert loop.

## Deviations from Plan
- Two additional bug fixes discovered and resolved during UAT (both in application code, not the verification script)

---
*Phase: 18-manual-uat-and-bug-fixes*
*Completed: 2026-03-04*
