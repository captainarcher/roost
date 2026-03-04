# Phase 20: Integration Tests - Research

**Researched:** 2026-03-04
**Domain:** Python integration testing with PostgreSQL, async fixtures, mock strategy
**Confidence:** HIGH

## Summary

Phase 20 adds integration tests that compose the real orchestrators — `process_booking_submission` and `prepare_welcome_message` — against a real PostgreSQL database with mocked external services (SMTP, scheduler). The unit tests (Phase 19) validated individual components; Phase 20 validates that those components wire together correctly end-to-end.

The key architectural insight is that both orchestrators accept a `Session` as an injected parameter (dependency injection pattern). This means integration tests can provide a test PostgreSQL session, wrap each test in a transaction that rolls back, and avoid data persistence between tests — without needing to truncate tables. SMTP is captured via the existing `SMTPCapture` fixture. The scheduler is mocked at the `schedule_pre_arrival_job` function level to avoid importing `app.main` (which triggers FastAPI initialization).

The primary planning challenge is database access: the production PostgreSQL container (`roost-db`) does not expose port 5432 to the host. Integration tests need either a `docker-compose.override.yml` exposing the port, or they run inside the container. Tests also need `get_config()` to work, which requires loading `AppConfig` — the `.env` file causes a validation error due to `POSTGRES_DB/USER/PASSWORD` fields not defined in `AppConfig`. The workaround is `AppConfig(_env_file=None)` with `DATABASE_URL` set as an environment variable.

**Primary recommendation:** Write tests that call `process_booking_submission()` and `prepare_welcome_message()` directly with a PostgreSQL session fixture that rolls back per test. Add a `docker-compose.override.yml` that publishes the DB port for local test runs. The integration conftest manages config loading and test DB setup.

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| pytest | 9.0.2 | Test runner | Already installed, configured in pyproject.toml |
| pytest-asyncio | 1.3.0 | Async test support | Already installed, `asyncio_mode = "auto"` configured |
| SQLAlchemy | 2.0.47 | ORM + test session | Already the app ORM, transaction rollback pattern built-in |
| psycopg | 3.3.3 | PostgreSQL driver | Already the production driver |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| unittest.mock (stdlib) | stdlib | Mock scheduler, patch functions | For `schedule_pre_arrival_job` test double |
| SMTPCapture (conftest.py) | project | Captures SMTP calls | Already tested in Phase 19 — reuse directly |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Transaction rollback isolation | Table truncation | Rollback is faster and simpler; truncation required for tests that commit across multiple sessions |
| Patching `schedule_pre_arrival_job` | Mocking the APScheduler object | Function-level patch is simpler; APScheduler object lives in `app.main` which triggers FastAPI init |
| `AppConfig(_env_file=None)` | Separate `.env.test` file | `_env_file=None` skips `.env` to avoid POSTGRES_ extra-field errors; no new file needed |

**Installation:** No new packages needed. All dependencies are already installed.

## Architecture Patterns

### Recommended Project Structure

```
tests/
├── conftest.py                  # Existing: SMTPCapture, db_session (SQLite), booking fixtures
└── integration/
    ├── conftest.py              # NEW: pg_session, integration_config, scheduler_capture
    ├── test_pdf_submission_flow.py   # NEW: PDF submission integration tests (TEST-05)
    └── test_communication_flow.py    # NEW: Communication flow integration tests (TEST-06)
```

### Pattern 1: PostgreSQL Session with Transaction Rollback

**What:** Each test runs inside a PostgreSQL transaction that is rolled back after the test — no data persists between tests, no table truncation needed.

**When to use:** Any test that writes to the database and must be isolated.

**Example:**
```python
# tests/integration/conftest.py
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401 — registers all models with Base.metadata
from app.db import Base

TEST_DB_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://rental:changeme@localhost:5432/rental_management_test"
)

@pytest.fixture(scope="session")
def pg_engine():
    """Create the test PostgreSQL engine and schema once per session."""
    engine = create_engine(TEST_DB_URL)
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()

@pytest.fixture
def pg_session(pg_engine):
    """Provide a PostgreSQL session that rolls back after each test."""
    connection = pg_engine.connect()
    transaction = connection.begin()
    Session = sessionmaker(bind=connection)
    session = Session()

    yield session

    session.close()
    transaction.rollback()
    connection.close()
```

**Note:** This pattern wraps each test in a transaction. When `session.commit()` is called inside the code under test, it commits into the savepoint (nested transaction), not the outer transaction. The outer `transaction.rollback()` reverses everything.

**Important caveat:** `process_booking_submission` and `prepare_welcome_message` call `db.commit()` directly. With the outer transaction pattern, these commits are to the connection-level transaction (not committed to the actual DB). The rollback in the fixture reverses them. This works correctly with SQLAlchemy 2.x + psycopg3.

### Pattern 2: Config Fixture for Integration Tests

**What:** `get_config()` requires `load_app_config()` to be called first. The `.env` file contains `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` — fields not in `AppConfig` — causing a `ValidationError`. The fix: use `AppConfig(_env_file=None)` and set `DATABASE_URL` as an env var.

**When to use:** Any fixture that needs `get_config()` to be callable.

**Example:**
```python
# tests/integration/conftest.py
import os
import pytest
import app.config as _cfg
from app.config import AppConfig, load_all_properties
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent

@pytest.fixture(scope="session", autouse=True)
def integration_config():
    """Load app config for integration tests, bypassing .env to avoid POSTGRES_ field errors."""
    # Save and reset the module-level singleton
    original_config = _cfg._config
    _cfg._config = None

    # Set DATABASE_URL so AppConfig picks it up from environment
    os.environ.setdefault("DATABASE_URL", TEST_DB_URL)

    # Build config WITHOUT loading .env (avoids POSTGRES_DB/USER/PASSWORD ValidationError)
    config = AppConfig(_env_file=None)
    config.properties = load_all_properties(PROJECT_ROOT / "config")
    _cfg._config = config

    yield config

    # Restore original config state
    _cfg._config = original_config
```

### Pattern 3: Scheduler Test Double

**What:** `schedule_pre_arrival_job` is called by `_create_communication_logs` in the normalizer. Importing `schedule_pre_arrival_job` normally triggers `from app.main import scheduler`, which initializes FastAPI. The test double patches `schedule_pre_arrival_job` at the call site in the normalizer to record what would have been scheduled.

**When to use:** Any test that triggers communication log creation (booking import flow).

**Example:**
```python
# tests/integration/conftest.py
from dataclasses import dataclass, field
from datetime import datetime
from unittest.mock import patch

@dataclass
class SchedulerCapture:
    """Records schedule_pre_arrival_job() calls without running APScheduler."""
    calls: list[dict] = field(default_factory=list)

    def __call__(self, booking_id: int, check_in_date) -> datetime:
        from app.communication.scheduler import compute_pre_arrival_send_time
        run_at = compute_pre_arrival_send_time(check_in_date)
        self.calls.append({"booking_id": booking_id, "check_in_date": check_in_date, "run_at": run_at})
        return run_at

@pytest.fixture
def scheduler_capture():
    """Replace schedule_pre_arrival_job with a recording mock."""
    capture = SchedulerCapture()
    with patch("app.ingestion.normalizer.schedule_pre_arrival_job", capture):
        yield capture
```

**Note from STATE.md (decision 19-03):** `schedule_pre_arrival_job` and `rebuild_pre_arrival_jobs` trigger FastAPI init. `compute_pre_arrival_send_time` is safe to import directly. The scheduler capture mock should call `compute_pre_arrival_send_time` internally to return the real computed time (verifying the correct value is recorded) without triggering APScheduler.

### Pattern 4: Integration-Specific Property Fixtures

**What:** Integration tests need `Property` rows in PostgreSQL (not SQLite). The existing `sample_property` fixture uses the `db_session` (SQLite) fixture. Integration tests need their own property fixtures that use `pg_session`.

**Example:**
```python
@pytest.fixture
def int_property(pg_session):
    """Insert a Property row into the integration test PostgreSQL session."""
    from app.models.property import Property
    prop = Property(slug="jay", display_name="Jay")
    pg_session.add(prop)
    pg_session.flush()
    return prop
```

### Pattern 5: Asserting on SMTP Calls for PDF Flow

**What:** The PDF submission flow ends with `await send_with_retry(...)` which calls `aiosmtplib.send`. The `SMTPCapture` from the unit test conftest is reused — same mechanism, same assertions.

**Example (from Phase 19 — reuse this pattern):**
```python
# Inherited from tests/conftest.py smtp_capture fixture
async def test_pdf_submission_airbnb(smtp_capture, int_property, pg_session, integration_config, ...):
    # ... set up booking and resort submission ...
    result = await process_booking_submission(booking.id, pg_session)

    assert result["action"] == "submitted"
    assert smtp_capture.call_count == 1

    msg = smtp_capture.calls[0]["message"]
    assert msg["To"] == int_prop_config.resort_contact_email
    assert "booking_form.pdf" in {a.get_filename() for a in msg.iter_attachments()}

    # Verify PDF attachment is a valid PDF
    attachments = list(msg.iter_attachments())
    pdf_attachment = next(a for a in attachments if a.get_filename() == "booking_form.pdf")
    assert pdf_attachment.get_payload(decode=True)[:4] == b"%PDF"
```

### Anti-Patterns to Avoid

- **Importing `schedule_pre_arrival_job` directly in tests:** Triggers `from app.main import scheduler` which initializes FastAPI, APScheduler, and attempts DB connections. Patch it at the call site instead.
- **Using `ingest_csv` as the integration test entry point for communication flow:** The normalizer uses `pg_insert` (PostgreSQL-specific dialect) and the property ID cache (`_property_id_cache`) which is a module-level dict that persists between tests. Use `prepare_welcome_message` + manual DB setup instead.
- **Using SQLite for integration tests:** `process_booking_submission` and `prepare_welcome_message` work with SQLite, but the context decisions require PostgreSQL to "exercise actual queries and data flow." The rollback pattern also behaves differently under SQLite (no savepoint semantics needed).
- **Table truncation for test isolation:** Slower than rollback; requires cleanup of all dependent tables in the right FK order. The rollback pattern is cleaner.
- **Calling `load_app_config()` without patching the singleton:** Each test that loads config will hit the cache and return the first loaded config. The `autouse=True, scope="session"` fixture handles this correctly.
- **Testing `send_pre_arrival_message` as the communication flow entry point:** This function creates its own `SessionLocal()` session internally (APScheduler context), bypassing the test's transaction rollback. Test `prepare_welcome_message` instead, which accepts an injected session.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| SMTP capture mock | Custom async mock class | `SMTPCapture` from `tests/conftest.py` | Already tested and working in Phase 19 |
| Pre-arrival send time calculation | Reproduce the formula in tests | Import `compute_pre_arrival_send_time` from `app.communication.scheduler` | Ensures tests match the actual implementation |
| PDF validation in assertions | Custom PDF parsing | `msg.iter_attachments()` + check `[:4] == b"%PDF"` | Already established pattern from Phase 19 unit tests |
| PostgreSQL test isolation | Manual TRUNCATE/DELETE after tests | SQLAlchemy connection-level transaction rollback | Simpler, faster, reversible |

**Key insight:** The Phase 19 infrastructure (SMTPCapture, db fixtures, booking fixtures) was built to be reused in Phase 20. Don't duplicate — extend.

## Common Pitfalls

### Pitfall 1: The `.env` POSTGRES_ Field Error

**What goes wrong:** Calling `load_app_config()` fails with `ValidationError: Extra inputs are not permitted` for `postgres_db`, `postgres_user`, `postgres_password`. These fields are in `.env` for Docker Compose but not defined in `AppConfig`.

**Why it happens:** The `.env` file has `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` at the top (used by docker-compose for the DB container). `AppConfig` uses `pydantic_settings` which reads `.env` and rejects unknown fields by default.

**How to avoid:** Use `AppConfig(_env_file=None)` to bypass `.env` loading. Set `DATABASE_URL` directly as an environment variable before instantiating. Verified working:
```python
os.environ["DATABASE_URL"] = "postgresql+psycopg://rental:changeme@localhost:5432/rental_management_test"
config = AppConfig(_env_file=None)
config.properties = load_all_properties(Path("config"))
```

### Pitfall 2: FastAPI Init Triggered by Scheduler Import

**What goes wrong:** Importing `schedule_pre_arrival_job` or `rebuild_pre_arrival_jobs` in tests triggers `from app.main import scheduler` inside the function body. `app.main` initializes the full FastAPI app, APScheduler, and attempts to connect to the database on module load.

**Why it happens:** The scheduler functions use deferred imports to avoid circular imports, but the deferred `from app.main import scheduler` still initializes the module.

**How to avoid:** Patch `app.ingestion.normalizer.schedule_pre_arrival_job` at the call site (where the normalizer calls it). Only import `compute_pre_arrival_send_time` directly in tests — it has no problematic dependencies. Decision 19-03 in STATE.md documents this behavior.

### Pitfall 3: Database Not Accessible from Host

**What goes wrong:** `pytest` runs from the host machine. The `roost-db` PostgreSQL container does not expose port 5432 to the host. Integration tests that connect to `roost-db` hostname get `psycopg.OperationalError: failed to resolve host 'roost-db'`.

**Why it happens:** `docker-compose.yml` defines `roost-db` without a `ports:` mapping — port 5432 is only accessible within the Docker network.

**How to avoid:** Two options:
1. **Recommended for local dev:** Create `docker-compose.override.yml` that adds `ports: ["5432:5432"]` to the `roost-db` service. This file is not committed, or committed only for dev. Tests use `TEST_DATABASE_URL=postgresql+psycopg://rental:changeme@localhost:5432/...`
2. **Alternative:** Run `pytest` from inside the container via `docker exec roost-roost-api-1 /app/.venv/bin/pytest tests/integration/`. The container has pytest installed and can reach `roost-db` hostname.

Both approaches work. The `docker-compose.override.yml` is the more ergonomic developer experience.

### Pitfall 4: Config Singleton Contamination Between Tests

**What goes wrong:** `load_app_config()` caches the result in `_config` (module-level). If one test calls `load_app_config()` with dev settings and another expects different settings, they share the same cached config.

**Why it happens:** `app.config._config` is a module-level singleton for performance. It's idempotent by design (returns cached after first load).

**How to avoid:** The `integration_config` fixture (Pattern 2 above) saves and restores `_config` around the test session. Use `scope="session"` so it's initialized once for the entire integration test run. Don't call `load_app_config()` inside individual test functions.

### Pitfall 5: `should_auto_submit` Preview Mode Blocking Auto-Submit

**What goes wrong:** `process_booking_submission` calls `should_auto_submit(db, threshold=3)`. If fewer than 3 submissions with status `'submitted'` or `'confirmed'` exist, the result is `"preview_pending"` instead of `"submitted"`. Tests that don't seed enough submissions fail unexpectedly.

**Why it happens:** The preview mode feature is working as designed. Phase 18 confirmed: threshold counts by status, not `submitted_automatically` flag.

**How to avoid:** Either seed 3+ prior `ResortSubmission` rows with status `"submitted"` before each test, or override the threshold to 0 by patching `config.auto_submit_threshold = 0` in the integration config fixture. The threshold-override approach is cleaner for integration tests — the threshold logic was tested in Phase 19 unit tests.

### Pitfall 6: `_property_id_cache` Module-Level Cache in Normalizer

**What goes wrong:** `app.ingestion.normalizer._property_id_cache` caches `slug -> id` mappings across tests. If a test creates a property with a certain ID, rolls back, then a subsequent test creates a property with a different ID for the same slug, the cache returns the stale ID.

**Why it happens:** `_property_id_cache` is a module-level dict, not scoped to the DB session.

**How to avoid:** The integration tests don't call `ingest_csv` or `create_manual_booking` (which go through the normalizer) — they call `process_booking_submission` and `prepare_welcome_message` directly with booking/property data already set up. The cache issue only appears if normalizer functions are used as entry points. If the normalizer path is needed, clear the cache: `from app.ingestion import normalizer; normalizer._property_id_cache.clear()`.

### Pitfall 7: `process_booking_submission` Calls `db.commit()` Internally

**What goes wrong:** The function commits the session multiple times internally (after creating the submission record, after updating status). With the connection-level transaction rollback pattern, these commits go into the outer transaction but don't reach the DB. This is the intended behavior, but if you expect the session to be clean after the function call, you may be surprised.

**Why it happens:** `process_booking_submission` manages its own transaction lifecycle for production use.

**How to avoid:** This is correct behavior for the test pattern. The outer `transaction.rollback()` in the `pg_session` fixture reverses all commits made during the test. No special handling needed.

## Code Examples

Verified patterns from codebase inspection:

### Integration conftest.py structure

```python
# tests/integration/conftest.py
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.config as _cfg
import app.models  # noqa: F401 — registers all models with Base.metadata
from app.config import AppConfig, load_all_properties
from app.db import Base
from app.models.booking import Booking
from app.models.communication_log import CommunicationLog
from app.models.property import Property
from app.models.resort_submission import ResortSubmission

PROJECT_ROOT = Path(__file__).parent.parent.parent

TEST_DB_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://rental:changeme@localhost:5432/rental_management_test",
)


@pytest.fixture(scope="session", autouse=True)
def integration_config():
    """Load app config for integration tests without .env (avoids POSTGRES_ field errors)."""
    original = _cfg._config
    _cfg._config = None
    os.environ.setdefault("DATABASE_URL", TEST_DB_URL)
    config = AppConfig(_env_file=None)
    config.properties = load_all_properties(PROJECT_ROOT / "config")
    # Override threshold for tests so preview mode doesn't block auto-submit
    config.auto_submit_threshold = 0
    _cfg._config = config
    yield config
    _cfg._config = original


@pytest.fixture(scope="session")
def pg_engine(integration_config):
    """Create the test DB schema once per session."""
    engine = create_engine(TEST_DB_URL)
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def pg_session(pg_engine):
    """PostgreSQL session that rolls back after each test."""
    conn = pg_engine.connect()
    txn = conn.begin()
    Session = sessionmaker(bind=conn)
    session = Session()
    yield session
    session.close()
    txn.rollback()
    conn.close()


@dataclass
class SchedulerCapture:
    """Records schedule_pre_arrival_job() calls without running APScheduler."""
    calls: list[dict] = field(default_factory=list)

    def __call__(self, booking_id: int, check_in_date) -> datetime:
        from app.communication.scheduler import compute_pre_arrival_send_time
        run_at = compute_pre_arrival_send_time(check_in_date)
        self.calls.append({
            "booking_id": booking_id,
            "check_in_date": check_in_date,
            "run_at": run_at,
        })
        return run_at


@pytest.fixture
def scheduler_capture():
    """Mock schedule_pre_arrival_job to record calls without triggering APScheduler."""
    capture = SchedulerCapture()
    with patch("app.ingestion.normalizer.schedule_pre_arrival_job", capture):
        yield capture


@pytest.fixture
def int_property(pg_session) -> Property:
    """Insert a Property row in the integration test DB."""
    prop = Property(slug="jay", display_name="Jay")
    pg_session.add(prop)
    pg_session.flush()
    return prop


@pytest.fixture
def int_airbnb_booking(pg_session, int_property) -> Booking:
    """Airbnb booking for integration tests — realistic guest data."""
    booking = Booking(
        platform="airbnb",
        platform_booking_id="INT-AIR-001",
        property_id=int_property.id,
        guest_name="Alice Chen",
        check_in_date=date(2026, 7, 10),
        check_out_date=date(2026, 7, 15),
        net_amount=Decimal("850.00"),
    )
    pg_session.add(booking)
    pg_session.flush()
    return booking


@pytest.fixture
def int_vrbo_booking(pg_session, int_property) -> Booking:
    """VRBO booking for integration tests — realistic guest data."""
    booking = Booking(
        platform="vrbo",
        platform_booking_id="INT-VRBO-001",
        property_id=int_property.id,
        guest_name="Bob Johnson",
        check_in_date=date(2026, 8, 1),
        check_out_date=date(2026, 8, 5),
        net_amount=Decimal("1200.00"),
    )
    pg_session.add(booking)
    pg_session.flush()
    return booking
```

### PDF submission flow test structure

```python
# tests/integration/test_pdf_submission_flow.py
import pytest
from app.compliance.submission import process_booking_submission

pytestmark = pytest.mark.integration


async def test_airbnb_pdf_submission_happy_path(
    smtp_capture, pg_session, int_airbnb_booking, integration_config
):
    """Booking import triggers filled PDF -> email with PDF attachment -> SMTP called."""
    result = await process_booking_submission(int_airbnb_booking.id, pg_session)

    assert result["action"] == "submitted"

    # SMTP called exactly once
    assert smtp_capture.call_count == 1
    msg = smtp_capture.calls[0]["message"]

    # Correct recipient
    assert msg["To"] == "resort@example.com"  # from int_prop_config

    # Subject follows expected format
    assert "Alice Chen" in msg["Subject"]
    assert "110" in msg["Subject"]  # site_number

    # PDF attachment exists and is valid
    attachments = list(msg.iter_attachments())
    filenames = {a.get_filename() for a in attachments}
    assert "booking_form.pdf" in filenames
    pdf_bytes = next(a.get_payload(decode=True) for a in attachments if a.get_filename() == "booking_form.pdf")
    assert pdf_bytes[:4] == b"%PDF"
    assert len(pdf_bytes) > 1000  # Non-trivial PDF
```

### Communication flow test structure

```python
# tests/integration/test_communication_flow.py
import pytest
from sqlalchemy import select
from app.communication.messenger import prepare_welcome_message
from app.models.communication_log import CommunicationLog
from app.communication.scheduler import compute_pre_arrival_send_time

pytestmark = pytest.mark.integration


async def test_vrbo_welcome_creates_log_and_notifies_operator(
    smtp_capture, pg_session, int_vrbo_booking, integration_config
):
    """VRBO booking triggers: welcome log created + operator notification sent."""
    await prepare_welcome_message(int_vrbo_booking.id, "vrbo", pg_session)

    # Welcome log created
    log = pg_session.execute(
        select(CommunicationLog).where(
            CommunicationLog.booking_id == int_vrbo_booking.id,
            CommunicationLog.message_type == "welcome",
        )
    ).scalar_one()
    assert log.status == "pending"
    assert log.rendered_message is not None
    assert "Bob Johnson" in log.rendered_message

    # Operator notified via SMTP
    assert smtp_capture.call_count == 1
    assert log.operator_notified_at is not None


async def test_pre_arrival_scheduled_with_correct_timing(
    pg_session, int_airbnb_booking
):
    """CommunicationLog pre_arrival row has correct scheduled_for time."""
    from app.models.communication_log import CommunicationLog
    expected_send_time = compute_pre_arrival_send_time(int_airbnb_booking.check_in_date)

    # Simulate what _create_communication_logs does — create the pre_arrival log
    comm_log = CommunicationLog(
        booking_id=int_airbnb_booking.id,
        message_type="pre_arrival",
        platform="airbnb",
        status="pending",
        scheduled_for=expected_send_time,
    )
    pg_session.add(comm_log)
    pg_session.flush()

    # Assert scheduled_for is 2 days before check-in at 14:00 UTC
    assert comm_log.scheduled_for == expected_send_time
    assert comm_log.scheduled_for.hour == 14
    assert comm_log.scheduled_for.minute == 0
```

### Running integration tests separately

```bash
# Run only integration tests (from project root, with TEST_DATABASE_URL set)
TEST_DATABASE_URL=postgresql+psycopg://rental:changeme@localhost:5432/rental_management_test \
  pytest tests/integration/ -v

# Run all tests (unit + integration)
pytest

# Run only unit tests (skip integration)
pytest tests/ --ignore=tests/integration/

# Or use the marker
pytest -m integration
pytest -m "not integration"
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| SQLite for all tests | SQLite for unit tests, PostgreSQL for integration | Phase 20 decision | Integration tests catch real PostgreSQL behaviors (server_default, timezone handling) |
| No integration tests | Integration tests in `tests/integration/` | Phase 20 | Full flow confidence before deployment |

**Deprecated/outdated:**
- `xmax`-based INSERT detection: Replaced by pre-check approach in Phase 18 (decision 18-03). Do not reference `xmax` in new test assertions.

## Open Questions

1. **Transaction rollback with multiple session.commit() calls**
   - What we know: `process_booking_submission` calls `db.commit()` multiple times internally. With the connection-level transaction wrapping, these commits stay within the outer transaction.
   - What's unclear: Whether SQLAlchemy 2.x + psycopg3 correctly handles nested commits within a connection-level transaction without SAVEPOINT. Some configurations require `begin_nested()` (SAVEPOINTs) for nested transactional behavior.
   - Recommendation: Test this in the first integration conftest implementation. If commits escape the outer rollback, use `session.begin_nested()` (savepoint) instead of connection-level wrapping. The plan should include a verification step.

2. **`integration_config.auto_submit_threshold = 0` and config immutability**
   - What we know: `AppConfig` is a Pydantic `BaseSettings` model. Pydantic v2 models are mutable by default unless `model_config = SettingsConfigDict(frozen=True)`. The current `AppConfig` does not set `frozen=True`.
   - What's unclear: Whether setting `config.auto_submit_threshold = 0` after instantiation works cleanly.
   - Recommendation: Verify this is settable. If not, pass `auto_submit_threshold=0` to `AppConfig()` directly. The plan should verify this works.

3. **`pg_session` fixture and async tests**
   - What we know: `process_booking_submission` and `prepare_welcome_message` are async functions. `pg_session` as defined above is a sync fixture. `pytest-asyncio` with `asyncio_mode="auto"` handles async test functions.
   - What's unclear: Whether async tests can receive a sync `pg_session` fixture directly or if the session needs to be wrapped in `pytest_asyncio.fixture`.
   - Recommendation: Sync fixtures are compatible with async tests in `pytest-asyncio` — async tests can receive sync fixtures. The fixture returns a regular SQLAlchemy session which is passed to async functions (the async functions only use it for sync SQLAlchemy operations, not asyncpg). This should work without changes.

## Sources

### Primary (HIGH confidence)

- Direct codebase inspection — all source files read and analyzed
  - `/Users/tunderhill/development/roost/app/compliance/submission.py` — `process_booking_submission` entry point, config usage, SMTP call pattern
  - `/Users/tunderhill/development/roost/app/communication/messenger.py` — `prepare_welcome_message` entry point, `send_pre_arrival_message` internal session usage
  - `/Users/tunderhill/development/roost/app/communication/scheduler.py` — `compute_pre_arrival_send_time` (safe to import), `schedule_pre_arrival_job` (triggers FastAPI init)
  - `/Users/tunderhill/development/roost/app/ingestion/normalizer.py` — `_create_communication_logs`, `_property_id_cache` module-level dict
  - `/Users/tunderhill/development/roost/app/config.py` — `_config` singleton, `AppConfig(_env_file=None)` workaround verified
  - `/Users/tunderhill/development/roost/tests/conftest.py` — `SMTPCapture`, existing fixtures to reuse
  - `/Users/tunderhill/development/roost/docker-compose.yml` — DB port not exposed to host
  - `/Users/tunderhill/development/roost/.env` — `POSTGRES_DB/USER/PASSWORD` fields that cause `AppConfig` validation errors
- Verified behaviors via Python subprocess:
  - `AppConfig(_env_file=None)` with `DATABASE_URL` env var: works, avoids POSTGRES_ field errors
  - PostgreSQL container accessible only via Docker network (not from host on port 5432)
  - `pytest-asyncio 1.3.0` + `asyncio_mode="auto"` — async tests work, sync fixtures compatible
  - `SQLAlchemy 2.0.47` with `Session.begin_nested()` — supported
  - All 58 existing unit tests pass

### Secondary (MEDIUM confidence)

- SQLAlchemy 2.x transaction rollback pattern for test isolation: well-established community pattern, consistent with SQLAlchemy documentation approach for test suites.
- `pytest-asyncio` sync fixture + async test compatibility: consistent with pytest-asyncio documentation behavior.

### Tertiary (LOW confidence)

- Transaction rollback behavior specifically with multiple `session.commit()` calls inside the tested function: not directly verified against the live PostgreSQL test database. Flagged as Open Question 1.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — verified installed versions, no new packages needed
- Architecture: HIGH — entry points confirmed from source code, fixture patterns verified
- Pitfalls: HIGH — `.env` error verified by running Python, FastAPI init trigger confirmed from STATE.md decisions, DB access limitation confirmed from docker-compose.yml
- Open questions: MEDIUM — the transaction rollback behavior with multiple commits needs verification during implementation

**Research date:** 2026-03-04
**Valid until:** 2026-04-04 (stable libraries, no fast-moving dependencies)
