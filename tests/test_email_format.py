"""Unit tests for email subject/body formatting, confirmation file matching,
SMTP email composition, and Phase 18-02 regression for should_auto_submit().

Tests:
  - format_email_subject: same-month and cross-month date formatting
  - format_email_body: includes contact name and sender sign-off
  - find_confirmation_file: found, case-insensitive, not-found, missing-dir
  - send_resort_email: attachments, TLS selection (smtp_capture fixture)
  - REGRESSION 18-02: should_auto_submit() counts by status, not submitted_automatically flag
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.compliance.confirmation import (
    find_confirmation_file,
    format_email_body,
    format_email_subject,
)
from app.compliance.emailer import send_resort_email
from app.compliance.submission import should_auto_submit
from app.models.booking import Booking
from app.models.resort_submission import ResortSubmission


# ---------------------------------------------------------------------------
# Subject line tests
# ---------------------------------------------------------------------------


def test_format_email_subject_same_month():
    result = format_email_subject(
        guest_name="Alice Chen",
        lot_number="110",
        check_in=date(2026, 7, 10),
        check_out=date(2026, 7, 15),
    )
    assert result == "Booking Form - Alice Chen - Lot 110 - Jul 10-15"


def test_format_email_subject_cross_month():
    result = format_email_subject(
        guest_name="Bob Johnson",
        lot_number="170",
        check_in=date(2026, 3, 31),
        check_out=date(2026, 4, 2),
    )
    assert result == "Booking Form - Bob Johnson - Lot 170 - Mar 31 - Apr 2"


@pytest.mark.parametrize(
    "check_in, check_out, expected_dates",
    [
        pytest.param(date(2026, 7, 1), date(2026, 7, 5), "Jul 1-5", id="same-month"),
        pytest.param(date(2026, 12, 29), date(2027, 1, 3), "Dec 29 - Jan 3", id="cross-month-year"),
        pytest.param(date(2026, 3, 1), date(2026, 3, 2), "Mar 1-2", id="single-day"),
    ],
)
def test_format_email_subject_various_dates(check_in, check_out, expected_dates):
    result = format_email_subject(
        guest_name="Test Guest",
        lot_number="110",
        check_in=check_in,
        check_out=check_out,
    )
    assert result.endswith(expected_dates), (
        f"Expected subject to end with {expected_dates!r}, got: {result!r}"
    )
    assert "Booking Form - Test Guest - Lot 110 - " in result


# ---------------------------------------------------------------------------
# Body tests
# ---------------------------------------------------------------------------


def test_format_email_body_includes_contact_name():
    result = format_email_body(contact_name="Jane")
    assert "Hi Jane" in result
    assert "booking form" in result.lower()
    assert "booking confirmation" in result.lower()


def test_format_email_body_includes_sender():
    result = format_email_body(contact_name="Jane", sender_name="Thomas")
    assert "Thomas" in result


# ---------------------------------------------------------------------------
# Confirmation file matching tests
# ---------------------------------------------------------------------------


def test_find_confirmation_file_found(tmp_path):
    conf_dir = tmp_path / "confirmations"
    conf_dir.mkdir()
    (conf_dir / "HMAB1234_confirmation.pdf").write_bytes(b"%PDF-fake")

    result = find_confirmation_file("HMAB1234", str(conf_dir))

    assert result is not None
    assert result.name == "HMAB1234_confirmation.pdf"


def test_find_confirmation_file_case_insensitive(tmp_path):
    conf_dir = tmp_path / "confirmations"
    conf_dir.mkdir()
    (conf_dir / "hmab5678_Booking.pdf").write_bytes(b"%PDF-fake")

    result = find_confirmation_file("HMAB5678", str(conf_dir))

    assert result is not None
    assert result.name == "hmab5678_Booking.pdf"


def test_find_confirmation_file_not_found(tmp_path):
    conf_dir = tmp_path / "confirmations"
    conf_dir.mkdir()

    result = find_confirmation_file("NONEXISTENT", str(conf_dir))

    assert result is None


def test_find_confirmation_file_missing_dir():
    result = find_confirmation_file("HMAB1234", "/nonexistent/path/confirmations")
    assert result is None


# ---------------------------------------------------------------------------
# SMTP email composition tests (smtp_capture fixture from conftest.py)
# ---------------------------------------------------------------------------


async def test_send_resort_email_with_both_attachments(smtp_capture):
    await send_resort_email(
        smtp_host="test",
        smtp_port=587,
        smtp_user="u",
        smtp_password="p",
        from_email="host@example.com",
        to_email="resort@example.com",
        subject="Test Subject",
        body="Test Body",
        form_bytes=b"fake-pdf-form",
        confirmation_bytes=b"fake-pdf-confirmation",
    )

    assert smtp_capture.call_count == 1

    msg = smtp_capture.calls[0]["message"]
    assert msg["From"] == "host@example.com"
    assert msg["To"] == "resort@example.com"
    assert msg["Subject"] == "Test Subject"

    attachments = list(msg.iter_attachments())
    assert len(attachments) == 2, f"Expected 2 attachments, got {len(attachments)}"

    filenames = {a.get_filename() for a in attachments}
    assert "booking_form.pdf" in filenames
    assert "booking_confirmation.pdf" in filenames


async def test_send_resort_email_without_confirmation(smtp_capture):
    await send_resort_email(
        smtp_host="test",
        smtp_port=587,
        smtp_user="u",
        smtp_password="p",
        from_email="host@example.com",
        to_email="resort@example.com",
        subject="Test Subject",
        body="Test Body",
        form_bytes=b"fake-pdf-form",
        confirmation_bytes=None,
    )

    msg = smtp_capture.calls[0]["message"]
    attachments = list(msg.iter_attachments())
    assert len(attachments) == 1, f"Expected 1 attachment, got {len(attachments)}"

    filenames = {a.get_filename() for a in attachments}
    assert "booking_form.pdf" in filenames
    assert "booking_confirmation.pdf" not in filenames


async def test_send_resort_email_tls_selection(smtp_capture):
    # Port 465 -> use_tls=True, start_tls=False
    await send_resort_email(
        smtp_host="test",
        smtp_port=465,
        smtp_user="u",
        smtp_password="p",
        from_email="host@example.com",
        to_email="resort@example.com",
        subject="Subject",
        body="Body",
        form_bytes=b"fake-pdf",
    )
    assert smtp_capture.calls[0]["kwargs"]["use_tls"] is True
    assert smtp_capture.calls[0]["kwargs"]["start_tls"] is False

    # Port 587 -> use_tls=False, start_tls=True
    await send_resort_email(
        smtp_host="test",
        smtp_port=587,
        smtp_user="u",
        smtp_password="p",
        from_email="host@example.com",
        to_email="resort@example.com",
        subject="Subject",
        body="Body",
        form_bytes=b"fake-pdf",
    )
    assert smtp_capture.calls[-1]["kwargs"]["use_tls"] is False
    assert smtp_capture.calls[-1]["kwargs"]["start_tls"] is True


# ---------------------------------------------------------------------------
# Phase 18-02 regression tests
# ---------------------------------------------------------------------------


def test_should_auto_submit_counts_manual_approvals(db_session, sample_property):
    """REGRESSION 18-02: A manually-approved submission (submitted_automatically=False,
    status='submitted') counts toward the threshold because threshold is based on
    status, NOT the submitted_automatically flag.
    """
    booking = Booking(
        platform="airbnb",
        platform_booking_id="REGTEST001",
        property_id=sample_property.id,
        guest_name="Test Guest",
        check_in_date=date(2026, 7, 10),
        check_out_date=date(2026, 7, 15),
        net_amount=Decimal("500.00"),
    )
    db_session.add(booking)
    db_session.flush()

    submission = ResortSubmission(
        booking_id=booking.id,
        status="submitted",
        submitted_automatically=False,  # manually approved
    )
    db_session.add(submission)
    db_session.flush()

    # Manual submission with status='submitted' MUST count toward threshold
    result = should_auto_submit(db_session, threshold=1)
    assert result is True, (
        "should_auto_submit() should return True when a manually-approved "
        "submission (status='submitted') exists and threshold=1"
    )


def test_should_auto_submit_pending_does_not_count(db_session, sample_property):
    """REGRESSION 18-02: A pending submission does NOT count toward the threshold,
    confirming the boundary: only 'submitted' and 'confirmed' statuses enable auto-submit.
    """
    booking = Booking(
        platform="airbnb",
        platform_booking_id="REGTEST002",
        property_id=sample_property.id,
        guest_name="Test Guest",
        check_in_date=date(2026, 7, 10),
        check_out_date=date(2026, 7, 15),
        net_amount=Decimal("500.00"),
    )
    db_session.add(booking)
    db_session.flush()

    submission = ResortSubmission(
        booking_id=booking.id,
        status="pending",
        submitted_automatically=False,
    )
    db_session.add(submission)
    db_session.flush()

    # Pending submission must NOT count toward threshold
    result = should_auto_submit(db_session, threshold=1)
    assert result is False, (
        "should_auto_submit() should return False when only pending submissions "
        "exist and threshold=1"
    )
