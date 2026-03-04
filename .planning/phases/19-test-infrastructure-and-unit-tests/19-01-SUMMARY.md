---
phase: 19-test-infrastructure-and-unit-tests
plan: "01"
subsystem: testing
tags: [pytest, pytest-asyncio, sqlalchemy, sqlite, aiosmtplib, conftest, fixtures]

# Dependency graph
requires:
  - phase: all prior phases
    provides: app.db.Base, app.models.*, app.config.PropertyConfig — all imported by conftest.py fixtures
provides:
  - pytest configured with asyncio_mode=auto in pyproject.toml
  - SMTPCapture dataclass + smtp_capture fixture (patches aiosmtplib.send globally)
  - db_session fixture (SQLite in-memory, all models, FK enforcement)
  - sample_property, sample_prop_config fixtures
  - sample_airbnb_booking, sample_vrbo_booking, sample_rvshare_booking fixtures
  - PROJECT_ROOT constant for resolving asset paths
affects:
  - 19-02-test-compliance-emailer
  - 19-03-test-communication-emailer
  - 20-integration-tests (any future test plans)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "pytest-asyncio asyncio_mode=auto: no @pytest.mark.asyncio decorator needed on async tests"
    - "SMTPCapture callable dataclass: monkeypatches aiosmtplib.send at module level, catches both emailer modules"
    - "SQLite in-memory db_session: per-test isolation via create_all/drop_all lifecycle"

key-files:
  created:
    - tests/conftest.py
  modified:
    - pyproject.toml

key-decisions:
  - "Patch aiosmtplib.send on the aiosmtplib module directly (not on individual importers) so both app.compliance.emailer and app.communication.emailer are intercepted with one monkeypatch"
  - "SMTPCapture stores raw EmailMessage objects (not headers) so tests can inspect headers, body, and attachments flexibly"
  - "SQLite PRAGMA foreign_keys=ON applied via SQLAlchemy event listener on engine connect for correctness"

patterns-established:
  - "smtp_capture fixture: tests assert smtp_capture.calls[0]['message']['Subject'], smtp_capture.call_count, smtp_capture.last_call()"
  - "db_session fixture: flush after add to get auto-assigned id before using in related fixtures"

# Metrics
duration: 2min
completed: 2026-03-04
---

# Phase 19 Plan 01: Test Infrastructure Setup Summary

**pytest infrastructure with in-memory SQLite db_session, global aiosmtplib.send SMTPCapture mock, and fabricated Airbnb/VRBO/RVshare booking fixtures — foundation for all Phase 19 and 20 tests**

## Performance

- **Duration:** ~2 min
- **Started:** 2026-03-04T19:58:47Z
- **Completed:** 2026-03-04T20:00:57Z
- **Tasks:** 1/1
- **Files modified:** 2

## Accomplishments

- pytest configured in pyproject.toml with `asyncio_mode = "auto"` so async tests require no decorator
- `tests/conftest.py` (205 lines) provides all shared fixtures for Phase 19 plans 02 and 03
- SMTPCapture patches `aiosmtplib.send` globally so both compliance and communication emailers are intercepted with one fixture
- All 3 smoke tests passed (db_session, smtp_capture, PROJECT_ROOT), smoke test file deleted after verification

## Task Commits

Each task was committed atomically:

1. **Task 1: Configure pytest in pyproject.toml and create conftest.py with shared fixtures** - `5b4b4fa` (chore)

**Plan metadata:** _(docs commit follows)_

## Files Created/Modified

- `tests/conftest.py` - Shared fixtures: SMTPCapture, smtp_capture, db_session, sample_property, sample_prop_config, sample_airbnb_booking, sample_vrbo_booking, sample_rvshare_booking, PROJECT_ROOT
- `pyproject.toml` - Added [tool.pytest.ini_options] with asyncio_mode=auto, asyncio_default_fixture_loop_scope=function, testpaths=["tests"], pypdf DeprecationWarning filter

## Decisions Made

- Patched `aiosmtplib.send` at the module attribute level (not at `app.compliance.emailer.aiosmtplib.send`) so a single `monkeypatch.setattr("aiosmtplib.send", capture)` intercepts both emailer modules that do `import aiosmtplib; await aiosmtplib.send(...)`.
- SMTPCapture stores the raw `email.message.EmailMessage` object rather than parsed fields, giving tests full access to headers via `msg["Subject"]`, attachments via `msg.iter_attachments()`, and body via `msg.get_body()`.
- Used SQLAlchemy event listener on `"connect"` to run `PRAGMA foreign_keys=ON` — the recommended pattern for per-connection SQLite pragmas.

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- Plan 19-02 (test-compliance-emailer) can import all fixtures from conftest.py immediately
- Plan 19-03 (test-communication-emailer) can import all fixtures from conftest.py immediately
- `pytest --collect-only` runs without errors from project root

---
*Phase: 19-test-infrastructure-and-unit-tests*
*Completed: 2026-03-04*
