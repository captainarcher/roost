# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-03-03)

**Core value:** Automated end-to-end rental operations — from booking notification to accounting entry — with zero manual intervention after initial configuration
**Current focus:** v1.2 Automation Verification & Testing — Phase 19

## Current Position

Phase: 19 of 20 (Test Infrastructure & Unit Tests)
Plan: 1 of 3 in current phase
Status: In progress
Last activity: 2026-03-04 — Completed 19-01 (Test Infrastructure Setup)

Progress: [████░░░░░░] ~50% (4/8 v1.2 plans complete)

## Performance Metrics

**v1.0 Milestone:**
- Total plans completed: 56
- Total phases: 13
- Timeline: 5 days (2026-02-26 -> 2026-03-02)

**v1.1 Milestone:**
- Total plans completed: 13
- Total phases: 4 (Phases 14-17)
- Timeline: 2 days (2026-03-02 -> 2026-03-04)

**v1.2 Milestone:**
- Total plans: 8 (3 + 3 + 2)
- Completed: 3 (Phase 18 done)

## Accumulated Context

### Decisions

All v1.0 decisions archived in `.planning/milestones/v1.0-ROADMAP.md`.
All v1.1 decisions archived in `.planning/milestones/v1.1-ROADMAP.md`.

Recent decisions affecting current work:
- v1.1: pypdf replaces PyMuPDF — verified working in Phase 18 with Helvetica font override
- 18-01: PDF fill uses /Helv override + auto_regenerate + read-only fields (CIDFont incompatible with pypdf)
- 18-02: Preview mode threshold counts successful sends (not submitted_automatically flag)
- 18-03: Normalizer INSERT detection uses pre-check approach (xmax unreliable with psycopg3)
- 19-01: smtp_capture patches aiosmtplib.send at module level (not per-importer) so both emailer modules are caught by one monkeypatch
- 19-01: SMTPCapture stores raw EmailMessage objects for flexible test inspection of headers, body, and attachments

### Pending Todos

None.

### Blockers/Concerns

None.

### Tech Debt Carried Forward

19 items total:
- 5 from v1.1 (see `.planning/milestones/v1.1-MILESTONE-AUDIT.md`)
- 14 from v1.0 (see `.planning/milestones/v1.0-MILESTONE-AUDIT.md`)

## Session Continuity

Last session: 2026-03-04T20:00:57Z
Stopped at: Completed 19-01-PLAN.md (Test Infrastructure Setup)
Resume file: None
Next action: Execute 19-02 (test-compliance-emailer)
