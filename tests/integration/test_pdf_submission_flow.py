"""Integration tests for the PDF submission flow.

Tests exercise process_booking_submission() end-to-end against a real
PostgreSQL database with mocked SMTP (via smtp_capture fixture).

Prerequisite: PostgreSQL test database must be running and accessible.
See tests/integration/conftest.py for setup instructions.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select

from app.compliance.submission import process_booking_submission
from app.config import get_config
from app.models.resort_submission import ResortSubmission

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_airbnb_pdf_submission_happy_path(
    pg_session,
    int_airbnb_booking,
    smtp_capture,
    integration_config,
):
    """Airbnb booking: filled PDF emailed to resort contact with correct headers and attachment.

    Verifies the full pipeline: booking lookup -> PDF fill -> email compose ->
    SMTP send -> ResortSubmission record updated.
    """
    result = await process_booking_submission(int_airbnb_booking.id, pg_session)

    # Function reports successful submission
    assert result["action"] == "submitted", f"Expected 'submitted', got: {result}"

    # SMTP called exactly once
    assert smtp_capture.call_count == 1
    msg = smtp_capture.calls[0]["message"]

    # Correct recipient -- matches resort_contact_email from jay.yaml
    prop_config = next(
        pc for pc in get_config().properties if pc.slug == "jay"
    )
    assert msg["To"] == prop_config.resort_contact_email

    # Subject follows expected format: "Booking Form - {guest} - Lot {number} - {dates}"
    subject = msg["Subject"]
    assert "Booking Form" in subject
    assert "Alice Chen" in subject
    assert "Lot 110" in subject

    # From email matches SMTP config
    assert msg["From"] == integration_config.smtp_from_email

    # PDF attachment exists and is a valid PDF (magic bytes %PDF)
    attachments = list(msg.iter_attachments())
    assert len(attachments) >= 1, "Expected at least one PDF attachment"
    pdf_bytes = attachments[0].get_payload(decode=True)
    assert pdf_bytes[:4] == b"%PDF", "First attachment must be a valid PDF"
    assert len(pdf_bytes) > 1000, "PDF attachment is unexpectedly small"

    # ResortSubmission row created with correct status
    submission = pg_session.execute(
        select(ResortSubmission).where(
            ResortSubmission.booking_id == int_airbnb_booking.id
        )
    ).scalar_one()
    assert submission.status == "submitted"
    assert submission.submitted_automatically is True
    assert submission.email_sent_at is not None


@pytest.mark.asyncio
async def test_vrbo_pdf_submission_happy_path(
    pg_session,
    int_vrbo_booking,
    smtp_capture,
    integration_config,
):
    """VRBO booking: filled PDF emailed to resort contact with correct subject and attachment.

    Verifies the VRBO platform variant produces a correctly addressed submission
    email with the right guest name in the subject.
    """
    result = await process_booking_submission(int_vrbo_booking.id, pg_session)

    assert result["action"] == "submitted", f"Expected 'submitted', got: {result}"

    # SMTP called exactly once
    assert smtp_capture.call_count == 1
    msg = smtp_capture.calls[0]["message"]

    # Correct recipient
    prop_config = next(
        pc for pc in get_config().properties if pc.slug == "jay"
    )
    assert msg["To"] == prop_config.resort_contact_email

    # Subject contains VRBO guest name and lot number
    subject = msg["Subject"]
    assert "Bob Johnson" in subject
    assert "Lot 110" in subject

    # PDF attachment present and valid
    attachments = list(msg.iter_attachments())
    assert len(attachments) >= 1, "Expected at least one PDF attachment"
    pdf_bytes = attachments[0].get_payload(decode=True)
    assert pdf_bytes[:4] == b"%PDF", "First attachment must be a valid PDF"

    # ResortSubmission row created
    submission = pg_session.execute(
        select(ResortSubmission).where(
            ResortSubmission.booking_id == int_vrbo_booking.id
        )
    ).scalar_one()
    assert submission.status == "submitted"


@pytest.mark.asyncio
async def test_submission_idempotent_skip(
    pg_session,
    int_airbnb_booking,
    smtp_capture,
):
    """Re-submitting a completed booking returns 'already_exists' without sending again.

    Verifies idempotency: calling process_booking_submission twice for the same
    booking does not send a duplicate email.
    """
    # First call succeeds
    first_result = await process_booking_submission(int_airbnb_booking.id, pg_session)
    assert first_result["action"] == "submitted"
    assert smtp_capture.call_count == 1

    # Clear capture to detect any second send
    smtp_capture.calls.clear()

    # Second call must short-circuit
    second_result = await process_booking_submission(int_airbnb_booking.id, pg_session)
    assert second_result["action"] == "already_exists", (
        f"Expected 'already_exists' on re-submission, got: {second_result}"
    )

    # No second email sent
    assert smtp_capture.call_count == 0, (
        "No SMTP call should be made for an already-submitted booking"
    )


@pytest.mark.asyncio
async def test_submission_booking_not_found(pg_session):
    """Submitting a non-existent booking ID returns an error action.

    Verifies that process_booking_submission handles missing bookings gracefully
    without raising an unhandled exception.
    """
    result = await process_booking_submission(99999, pg_session)

    assert result["action"] == "error", f"Expected 'error', got: {result}"
    assert "not found" in result.get("error", "").lower(), (
        f"Error message should mention 'not found': {result.get('error')}"
    )


@pytest.mark.asyncio
async def test_submission_with_confirmation_attachment(
    pg_session,
    int_airbnb_booking,
    smtp_capture,
    integration_config,
):
    """When a confirmation PDF exists, it is included as a second attachment.

    Verifies that find_confirmation_file() locates the confirmation PDF in the
    confirmations directory and it is attached alongside the filled booking form.
    """
    # Create a fake confirmation PDF in the configured confirmations directory
    confirmations_dir = Path(integration_config.confirmations_dir)
    confirmation_file = confirmations_dir / "INT-AIR-001_confirmation.pdf"
    fake_pdf_content = b"%PDF-1.4 fake confirmation"
    confirmation_file.write_bytes(fake_pdf_content)

    try:
        result = await process_booking_submission(int_airbnb_booking.id, pg_session)
        assert result["action"] == "submitted", f"Expected 'submitted', got: {result}"

        # SMTP called once
        assert smtp_capture.call_count == 1
        msg = smtp_capture.calls[0]["message"]

        # Should have 2 attachments: filled form + confirmation
        attachments = list(msg.iter_attachments())
        assert len(attachments) == 2, (
            f"Expected 2 attachments (form + confirmation), got {len(attachments)}"
        )

        # First attachment is the filled booking form (valid PDF)
        form_bytes = attachments[0].get_payload(decode=True)
        assert form_bytes[:4] == b"%PDF", "First attachment must be a valid PDF"

        # Second attachment is the confirmation (contains %PDF magic bytes)
        conf_bytes = attachments[1].get_payload(decode=True)
        assert b"%PDF" in conf_bytes, "Second attachment must contain PDF magic bytes"

        # ResortSubmission records confirmation_attached=True
        submission = pg_session.execute(
            select(ResortSubmission).where(
                ResortSubmission.booking_id == int_airbnb_booking.id
            )
        ).scalar_one()
        assert submission.confirmation_attached is True

    finally:
        # Clean up the fake confirmation file
        if confirmation_file.exists():
            confirmation_file.unlink()
