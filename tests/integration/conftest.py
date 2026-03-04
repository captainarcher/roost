# Prerequisite: CREATE DATABASE rental_management_test; must exist on the PostgreSQL server
# Run: psql -U rental -h localhost -c "CREATE DATABASE rental_management_test;"
#
# This conftest provides integration-test-specific fixtures that use a real
# PostgreSQL database (not SQLite). Each test runs inside a transaction that
# is rolled back after the test, so no data persists between tests.

from __future__ import annotations

import os
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.config as _cfg
import app.models  # noqa: F401 -- registers all models with Base.metadata
from app.config import AppConfig, load_all_properties
from app.db import Base
from app.models.booking import Booking
from app.models.property import Property

PROJECT_ROOT = Path(__file__).parent.parent.parent

TEST_DB_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://rental:changeme@localhost:5432/rental_management_test",
)


def pytest_configure(config):  # noqa: ANN001
    """Register the integration marker to suppress PytestUnknownMarkWarning."""
    config.addinivalue_line(
        "markers", "integration: integration tests requiring PostgreSQL"
    )


@pytest.fixture(scope="session", autouse=True)
def integration_config(tmp_path_factory):  # noqa: ANN001
    """Load app config for integration tests, bypassing .env to avoid POSTGRES_ field errors.

    - Sets DATABASE_URL env var to the test database URL.
    - Creates AppConfig(_env_file=None) to skip .env parsing (avoids
      POSTGRES_DB/USER/PASSWORD ValidationError from docker-compose fields).
    - Sets auto_submit_threshold=0 so preview mode is bypassed in all tests.
    - Sets SMTP fields to test values (no real emails sent).
    - Stores the config in app.config._config singleton.
    - Restores the original singleton value on teardown.
    """
    original = _cfg._config
    _cfg._config = None

    # Set DATABASE_URL so AppConfig picks it up from the environment
    os.environ.setdefault("DATABASE_URL", TEST_DB_URL)

    # Build config WITHOUT loading .env (avoids POSTGRES_ extra-field ValidationError)
    config = AppConfig(_env_file=None)
    config.properties = load_all_properties(PROJECT_ROOT / "config")

    # Override threshold so preview mode never blocks auto-submit in tests
    config.auto_submit_threshold = 0

    # SMTP test values -- no real emails sent (smtp_capture patches aiosmtplib.send)
    config.smtp_host = "localhost"
    config.smtp_port = 587
    config.smtp_user = "test@test.com"
    config.smtp_password = "testpass"
    config.smtp_from_email = "test@test.com"
    config.resort_contact_name = "Resort Staff"

    # PDF template paths -- use real files from project root
    config.pdf_template_path = str(PROJECT_ROOT / "pdf_mappings" / "sun_retreats_booking.pdf")
    config.pdf_mapping_path = str(PROJECT_ROOT / "pdf_mappings" / "sun_retreats_booking.json")

    # Confirmations dir -- use a temp directory so tests can place fake confirmation files
    confirmations_tmp = tmp_path_factory.mktemp("confirmations")
    config.confirmations_dir = str(confirmations_tmp)

    # Install as the global singleton
    _cfg._config = config

    yield config

    # Restore original config state
    _cfg._config = original


@pytest.fixture(scope="session")
def pg_engine(integration_config):  # noqa: ANN001
    """Create the test PostgreSQL engine and schema once per session.

    Creates all tables via Base.metadata.create_all(). Drops them on teardown.
    Requires the test database to already exist (see Prerequisite comment above).
    """
    engine = create_engine(TEST_DB_URL)
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def pg_session(pg_engine):  # noqa: ANN001
    """Provide a PostgreSQL session that rolls back after each test.

    Wraps each test in a connection-level transaction. Any commits made by
    the code under test go into this outer transaction, which is rolled back
    after the test. This ensures complete test isolation without table truncation.
    """
    conn = pg_engine.connect()
    txn = conn.begin()
    Session = sessionmaker(bind=conn)
    session = Session()

    yield session

    session.close()
    txn.rollback()
    conn.close()


@pytest.fixture
def int_property(pg_session) -> Property:  # noqa: ANN001
    """Insert a Property row for 'jay' into the integration test DB."""
    prop = Property(slug="jay", display_name="Jay")
    pg_session.add(prop)
    pg_session.flush()
    return prop


@pytest.fixture
def int_airbnb_booking(pg_session, int_property) -> Booking:  # noqa: ANN001
    """Airbnb booking for integration tests -- realistic guest data."""
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
def int_vrbo_booking(pg_session, int_property) -> Booking:  # noqa: ANN001
    """VRBO booking for integration tests -- realistic guest data."""
    booking = Booking(
        platform="vrbo",
        platform_booking_id="VRBO-INT-001",
        property_id=int_property.id,
        guest_name="Bob Johnson",
        check_in_date=date(2026, 8, 1),
        check_out_date=date(2026, 8, 5),
        net_amount=Decimal("1200.00"),
    )
    pg_session.add(booking)
    pg_session.flush()
    return booking
