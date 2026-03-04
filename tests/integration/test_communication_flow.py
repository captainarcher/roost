"""Integration tests for the guest communication flow.

Tests exercise the full guest communication pipeline end-to-end against a real
PostgreSQL database with mocked SMTP (smtp_capture) and mocked APScheduler
(scheduler_capture). Covers:

- Airbnb welcome: native_configured log, no email sent
- VRBO welcome: rendered template + operator notification email
- RVshare welcome: same operator notification path as VRBO
- Welcome message idempotency (second call is a no-op)
- Pre-arrival CommunicationLog creation with correct scheduled_for datetime
- Airbnb: both welcome and pre-arrival logs created together via _create_communication_logs

Prerequisite: PostgreSQL test database must be running and accessible.
See tests/integration/conftest.py for setup instructions.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.communication.messenger import prepare_welcome_message
from app.communication.scheduler import compute_pre_arrival_send_time
from app.ingestion.normalizer import _create_communication_logs
from app.models.booking import Booking
from app.models.communication_log import CommunicationLog

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_airbnb_welcome_native_configured(
    pg_session,
    int_airbnb_future_booking,
    smtp_capture,
):
    """Airbnb welcome: CommunicationLog created with status='native_configured', no email sent.

    Airbnb's own scheduled messaging handles welcome delivery automatically.
    The system only records that native messaging is configured -- no template
    is rendered and no operator notification is sent.
    """
    await prepare_welcome_message(
        int_airbnb_future_booking.id, "airbnb", pg_session
    )

    # Query for the welcome log
    log = pg_session.execute(
        select(CommunicationLog).where(
            CommunicationLog.booking_id == int_airbnb_future_booking.id,
            CommunicationLog.message_type == "welcome",
        )
    ).scalar_one_or_none()

    assert log is not None, "CommunicationLog for welcome should have been created"
    assert log.status == "native_configured", (
        f"Expected status='native_configured', got: {log.status!r}"
    )
    assert log.platform == "airbnb"
    assert log.rendered_message is None, (
        "Airbnb welcome should not have rendered_message (Airbnb handles natively)"
    )

    # No operator notification email sent for Airbnb welcome
    assert smtp_capture.call_count == 0, (
        f"Expected 0 SMTP calls for Airbnb welcome, got: {smtp_capture.call_count}"
    )


@pytest.mark.asyncio
async def test_vrbo_welcome_operator_notification(
    pg_session,
    int_vrbo_future_booking,
    smtp_capture,
):
    """VRBO welcome: template rendered, CommunicationLog created, operator notified by email.

    VRBO welcome messages require operator action -- the system renders the welcome
    text, stores it in the CommunicationLog, and emails the operator with copy-paste
    content for sending via the VRBO messaging interface.
    """
    await prepare_welcome_message(
        int_vrbo_future_booking.id, "vrbo", pg_session
    )

    # Query for the welcome log
    log = pg_session.execute(
        select(CommunicationLog).where(
            CommunicationLog.booking_id == int_vrbo_future_booking.id,
            CommunicationLog.message_type == "welcome",
        )
    ).scalar_one_or_none()

    assert log is not None, "CommunicationLog for welcome should have been created"
    assert log.status == "pending", (
        f"Expected status='pending' for VRBO welcome, got: {log.status!r}"
    )
    assert log.platform == "vrbo"

    # Template should have been rendered and stored
    assert log.rendered_message is not None, "rendered_message should not be None for VRBO welcome"
    assert len(log.rendered_message) > 0, "rendered_message should not be empty"

    # Guest name should appear in the rendered message
    assert "Carol Davis" in log.rendered_message, (
        "rendered_message should contain guest name 'Carol Davis'"
    )

    # Operator notified timestamp should be set
    assert log.operator_notified_at is not None, (
        "operator_notified_at should be set after email sent"
    )

    # Exactly one email sent (operator notification)
    assert smtp_capture.call_count == 1, (
        f"Expected exactly 1 SMTP call for VRBO welcome, got: {smtp_capture.call_count}"
    )

    # Inspect the captured email
    msg = smtp_capture.calls[0]["message"]

    # Subject contains platform display, guest name, and Welcome
    subject = msg["Subject"]
    assert "Welcome" in subject, f"Subject should contain 'Welcome': {subject!r}"
    assert "Carol Davis" in subject, f"Subject should contain guest name: {subject!r}"
    assert "VRBO" in subject, f"Subject should contain platform 'VRBO': {subject!r}"

    # Operator notification goes to the sender (operator email)
    assert msg["To"] == msg["From"], (
        f"To ({msg['To']!r}) should equal From ({msg['From']!r}) for operator notification"
    )

    # Email body contains guest name and rendered message content
    body_part = msg.get_body(preferencelist=("plain",))
    assert body_part is not None, "Email should have a plain text body"
    body_text = body_part.get_content()
    assert "Carol Davis" in body_text, "Email body should contain guest name"
    # The body includes the rendered welcome text (some portion should match)
    assert log.rendered_message[:50] in body_text or "Carol Davis" in body_text, (
        "Email body should contain rendered welcome text"
    )


@pytest.mark.asyncio
async def test_rvshare_welcome_operator_notification(
    pg_session,
    int_property,
    smtp_capture,
):
    """RVshare welcome: same operator notification path as VRBO.

    RVshare follows the same flow as VRBO -- the system renders the welcome
    template and emails the operator with copy-pasteable content. The email
    subject uses 'RVSHARE' (uppercased platform name).
    """
    # Create an RVshare booking inline
    booking = Booking(
        platform="rvshare",
        platform_booking_id="RVS-INT-001",
        property_id=int_property.id,
        guest_name="Eve Martinez",
        check_in_date=date(2026, 11, 1),
        check_out_date=date(2026, 11, 5),
        net_amount=Decimal("800.00"),
    )
    pg_session.add(booking)
    pg_session.flush()

    await prepare_welcome_message(booking.id, "rvshare", pg_session)

    # Query for the welcome log
    log = pg_session.execute(
        select(CommunicationLog).where(
            CommunicationLog.booking_id == booking.id,
            CommunicationLog.message_type == "welcome",
        )
    ).scalar_one_or_none()

    assert log is not None, "CommunicationLog for welcome should have been created"
    assert log.status == "pending", (
        f"Expected status='pending' for RVshare welcome, got: {log.status!r}"
    )
    assert log.platform == "rvshare"
    assert log.rendered_message is not None, "rendered_message should not be None for RVshare welcome"

    # Exactly one operator notification email sent
    assert smtp_capture.call_count == 1, (
        f"Expected exactly 1 SMTP call for RVshare welcome, got: {smtp_capture.call_count}"
    )

    # Email subject should use uppercased platform name
    msg = smtp_capture.calls[0]["message"]
    subject = msg["Subject"]
    assert "RVSHARE" in subject, (
        f"Subject should contain 'RVSHARE' (uppercased), got: {subject!r}"
    )


@pytest.mark.asyncio
async def test_welcome_idempotent(
    pg_session,
    int_vrbo_future_booking,
    smtp_capture,
):
    """Calling prepare_welcome_message twice creates only one log and sends only one email.

    The second call must detect the existing CommunicationLog and return immediately
    without creating a duplicate record or sending a second operator notification.
    """
    # First call: creates log and sends email
    await prepare_welcome_message(
        int_vrbo_future_booking.id, "vrbo", pg_session
    )
    assert smtp_capture.call_count == 1, "First call should send exactly 1 email"

    # Second call: should be a no-op
    await prepare_welcome_message(
        int_vrbo_future_booking.id, "vrbo", pg_session
    )

    # Still only one email sent total
    assert smtp_capture.call_count == 1, (
        f"Second call should not send another email, total calls: {smtp_capture.call_count}"
    )

    # Only one CommunicationLog row for this booking + welcome type
    count = pg_session.execute(
        select(func.count()).select_from(CommunicationLog).where(
            CommunicationLog.booking_id == int_vrbo_future_booking.id,
            CommunicationLog.message_type == "welcome",
        )
    ).scalar_one()
    assert count == 1, (
        f"Expected exactly 1 CommunicationLog for welcome, found: {count}"
    )


@pytest.mark.asyncio
async def test_pre_arrival_communication_log_created(
    pg_session,
    int_property,
    int_vrbo_future_booking,
    scheduler_capture,
):
    """VRBO _create_communication_logs creates pre-arrival log with correct scheduled_for datetime.

    Verifies that the normalizer's _create_communication_logs() function:
    1. Creates a CommunicationLog with message_type='pre_arrival' and status='pending'
    2. Sets scheduled_for to compute_pre_arrival_send_time(check_in_date) -- 2026-10-13 14:00 UTC
    3. Records the scheduling intent in scheduler_capture (patches schedule_pre_arrival_job)
    """
    # Call _create_communication_logs with the VRBO future booking
    _create_communication_logs(["VRBO-FUTURE-001"], "vrbo", pg_session)

    # Query for pre-arrival log
    log = pg_session.execute(
        select(CommunicationLog).where(
            CommunicationLog.booking_id == int_vrbo_future_booking.id,
            CommunicationLog.message_type == "pre_arrival",
        )
    ).scalar_one_or_none()

    assert log is not None, "Pre-arrival CommunicationLog should have been created"
    assert log.status == "pending", (
        f"Expected status='pending' for pre-arrival log, got: {log.status!r}"
    )
    assert log.scheduled_for is not None, "scheduled_for should not be None for pre-arrival"

    # Verify scheduled_for matches expected value: 2026-10-13 14:00 UTC (2 days before 2026-10-15)
    expected_run_at = compute_pre_arrival_send_time(date(2026, 10, 15))
    assert log.scheduled_for == expected_run_at, (
        f"scheduled_for mismatch: expected {expected_run_at}, got {log.scheduled_for}"
    )

    # Scheduler capture should have recorded the job
    assert len(scheduler_capture.calls) >= 1, (
        f"scheduler_capture should have at least 1 call, got: {len(scheduler_capture.calls)}"
    )

    # Find the call for this booking
    booking_calls = [
        c for c in scheduler_capture.calls
        if c["booking_id"] == int_vrbo_future_booking.id
    ]
    assert len(booking_calls) == 1, (
        f"Expected exactly 1 scheduler call for booking {int_vrbo_future_booking.id}"
    )
    recorded = booking_calls[0]
    assert recorded["run_at"] == expected_run_at, (
        f"scheduler_capture run_at mismatch: expected {expected_run_at}, got {recorded['run_at']}"
    )


@pytest.mark.asyncio
async def test_airbnb_pre_arrival_log_and_welcome_created_together(
    pg_session,
    int_property,
    int_airbnb_future_booking,
    scheduler_capture,
):
    """Airbnb _create_communication_logs creates both welcome and pre-arrival logs.

    For Airbnb, _create_communication_logs() creates TWO CommunicationLog rows:
    1. welcome: status='native_configured' (Airbnb handles delivery natively)
    2. pre_arrival: status='pending' with scheduled_for set to 2026-10-13 14:00 UTC

    The scheduler_capture records 1 pre-arrival job for this booking.
    """
    # Call _create_communication_logs with the Airbnb future booking
    _create_communication_logs(["AIR-FUTURE-001"], "airbnb", pg_session)

    # Query for all CommunicationLogs for this booking
    logs = pg_session.execute(
        select(CommunicationLog).where(
            CommunicationLog.booking_id == int_airbnb_future_booking.id,
        )
    ).scalars().all()

    assert len(logs) == 2, (
        f"Expected 2 CommunicationLog rows (welcome + pre_arrival) for Airbnb, got {len(logs)}"
    )

    # Find each log by message_type
    by_type = {log.message_type: log for log in logs}

    assert "welcome" in by_type, "welcome CommunicationLog should exist"
    assert "pre_arrival" in by_type, "pre_arrival CommunicationLog should exist"

    welcome_log = by_type["welcome"]
    pre_arrival_log = by_type["pre_arrival"]

    # Welcome log: native_configured status
    assert welcome_log.status == "native_configured", (
        f"Airbnb welcome log should have status='native_configured', got: {welcome_log.status!r}"
    )

    # Pre-arrival log: pending status with correct scheduled_for
    assert pre_arrival_log.status == "pending", (
        f"Pre-arrival log should have status='pending', got: {pre_arrival_log.status!r}"
    )
    expected_run_at = compute_pre_arrival_send_time(date(2026, 10, 15))
    assert pre_arrival_log.scheduled_for == expected_run_at, (
        f"pre_arrival scheduled_for mismatch: expected {expected_run_at}, "
        f"got {pre_arrival_log.scheduled_for}"
    )

    # Scheduler capture recorded exactly 1 job for this booking
    booking_calls = [
        c for c in scheduler_capture.calls
        if c["booking_id"] == int_airbnb_future_booking.id
    ]
    assert len(booking_calls) == 1, (
        f"Expected 1 scheduler call for Airbnb booking, got: {len(booking_calls)}"
    )
    assert booking_calls[0]["run_at"] == expected_run_at, (
        f"scheduler_capture run_at mismatch: expected {expected_run_at}, "
        f"got {booking_calls[0]['run_at']}"
    )
