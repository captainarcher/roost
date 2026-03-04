"""Shared pytest fixtures for the Roost test suite.

Provides:
  - SMTPCapture / smtp_capture: captures aiosmtplib.send() calls
  - db_session: in-memory SQLite session with all models created
  - sample_property: a Property ORM row
  - sample_prop_config: a PropertyConfig Pydantic object
  - sample_airbnb_booking / sample_vrbo_booking / sample_rvshare_booking
  - PROJECT_ROOT: path to the repository root
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401 — registers all models with Base.metadata
from app.config import PropertyConfig
from app.db import Base
from app.models.booking import Booking
from app.models.property import Property

# ---------------------------------------------------------------------------
# Project root constant — tests resolve paths to pdf_mappings/, templates/, etc.
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).parent.parent


# ---------------------------------------------------------------------------
# SMTP capture
# ---------------------------------------------------------------------------


@dataclass
class SMTPCapture:
    """Records every aiosmtplib.send() call made during a test.

    Each entry in ``calls`` is a dict with:
      - ``"message"``: the raw ``email.message.EmailMessage`` object
      - ``"kwargs"``:  keyword args passed (hostname, port, username, etc.)
    """

    calls: list[dict] = field(default_factory=list)

    async def __call__(self, msg, **kwargs) -> None:  # noqa: ANN001
        self.calls.append({"message": msg, "kwargs": kwargs})

    @property
    def call_count(self) -> int:
        """Number of send() calls recorded."""
        return len(self.calls)

    def last_call(self) -> dict:
        """Return the most recent captured call."""
        return self.calls[-1]


@pytest.fixture
def smtp_capture(monkeypatch) -> SMTPCapture:  # noqa: ANN001
    """Replace aiosmtplib.send with a no-op capture mock.

    Patches the module attribute on aiosmtplib directly so that both
    app.compliance.emailer and app.communication.emailer (which both
    import and call aiosmtplib.send) are intercepted.
    """
    capture = SMTPCapture()
    monkeypatch.setattr("aiosmtplib.send", capture)
    return capture


# ---------------------------------------------------------------------------
# Database fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def db_session():
    """Provide an in-memory SQLite session with all models created.

    Creates a fresh engine and schema for each test, tears down after.
    Foreign-key enforcement is enabled via PRAGMA for correctness.
    """
    engine = create_engine("sqlite:///:memory:", echo=False)

    # Enable FK enforcement for SQLite
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)

    Session = sessionmaker(bind=engine)
    session = Session()

    yield session

    session.close()
    Base.metadata.drop_all(engine)
    engine.dispose()


# ---------------------------------------------------------------------------
# Property fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_property(db_session):
    """Create and flush a Property row for "jay".

    Returns the ORM instance with its auto-assigned id.
    """
    prop = Property(slug="jay", display_name="Jay")
    db_session.add(prop)
    db_session.flush()
    return prop


@pytest.fixture
def sample_prop_config() -> PropertyConfig:
    """Return a PropertyConfig for testing — no DB or file system required."""
    return PropertyConfig(
        slug="jay",
        display_name="Jay",
        lock_code="1234",
        site_number="110",
        resort_contact_email="resort@example.com",
        resort_checkin_instructions=(
            "Check in at the Welcome Center upon arrival."
        ),
        host_name="Jane Smith",
        host_phone="555-123-4567",
        wifi_password="TestWifi123",
        address="123 Test Resort Way, Fort Myers Beach, FL 33931",
        check_in_time="4:00 PM",
        check_out_time="11:00 AM",
        parking_instructions="Park in the designated spot for your unit.",
        local_tips="Nearest grocery: Publix (0.5 mi).",
    )


# ---------------------------------------------------------------------------
# Booking fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_airbnb_booking(db_session, sample_property) -> Booking:
    """Fabricated Airbnb booking for "jay" property."""
    booking = Booking(
        platform="airbnb",
        platform_booking_id="HMTEST001",
        property_id=sample_property.id,
        guest_name="Alice Chen",
        check_in_date=date(2026, 7, 10),
        check_out_date=date(2026, 7, 15),
        net_amount=Decimal("850.00"),
    )
    db_session.add(booking)
    db_session.flush()
    return booking


@pytest.fixture
def sample_vrbo_booking(db_session, sample_property) -> Booking:
    """Fabricated VRBO booking for "jay" property."""
    booking = Booking(
        platform="vrbo",
        platform_booking_id="VRBO-TEST-001",
        property_id=sample_property.id,
        guest_name="Bob Johnson",
        check_in_date=date(2026, 8, 1),
        check_out_date=date(2026, 8, 5),
        net_amount=Decimal("1200.00"),
    )
    db_session.add(booking)
    db_session.flush()
    return booking


@pytest.fixture
def sample_rvshare_booking(db_session, sample_property) -> Booking:
    """Fabricated RVshare booking for "jay" property."""
    booking = Booking(
        platform="rvshare",
        platform_booking_id="RVS-TEST-001",
        property_id=sample_property.id,
        guest_name="Carol Davis",
        check_in_date=date(2026, 9, 15),
        check_out_date=date(2026, 9, 20),
        net_amount=Decimal("950.00"),
    )
    db_session.add(booking)
    db_session.flush()
    return booking
