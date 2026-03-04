"""Resort form submission orchestrator.

Coordinates the full submission pipeline:
1. Check preview mode (first N submissions require manual approval)
2. Fill resort PDF form from booking data + property config
3. Find platform booking confirmation file (optional)
4. Format email subject + body
5. Send email with retry
6. Update ResortSubmission record with outcome

Preview mode: The first `auto_submit_threshold` submissions (default 3) are
created with submitted_automatically=False and status='pending'. The operator
must approve them via the API before they are sent. After the threshold is
reached, new submissions auto-send immediately.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import select, func

from app.compliance.confirmation import (
    find_confirmation_file,
    format_email_body,
    format_email_subject,
)
from app.compliance.emailer import send_with_retry
from app.compliance.pdf_filler import fill_resort_form
from app.config import get_config
from app.models.booking import Booking
from app.models.property import Property
from app.models.resort_submission import ResortSubmission

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

log = structlog.get_logger()


def should_auto_submit(db: "Session", threshold: int = 3) -> bool:
    """Check if the system has passed the preview-mode threshold.

    Counts submissions with status 'submitted' or 'confirmed' (i.e. successfully
    sent). Once this count reaches the threshold, all future submissions are
    auto-sent without manual approval.

    The count is performed in the same transaction as the subsequent insert
    to prevent race conditions (two simultaneous bookings both reading count=2).

    Args:
        db: Active SQLAlchemy session (should be in a transaction).
        threshold: Number of successful submissions before preview mode ends.

    Returns:
        True if auto-submit is enabled (past threshold).
    """
    count = db.execute(
        select(func.count()).select_from(ResortSubmission).where(
            ResortSubmission.status.in_(("submitted", "confirmed"))
        )
    ).scalar_one()
    return count >= threshold


async def process_booking_submission(booking_id: int, db: "Session") -> dict:
    """Process a resort form submission for a booking.

    Full pipeline:
    1. Load booking + property data
    2. Check/create ResortSubmission record (idempotent -- skips if already exists)
    3. Check preview mode threshold
    4. If preview mode: leave as pending for manual approval
    5. If auto-submit: fill PDF, find confirmation, send email, update status

    Args:
        booking_id: ID of the booking to submit.
        db: Active SQLAlchemy session.

    Returns:
        Dict with submission status info:
        - action: "created_pending" | "submitted" | "failed" | "already_exists" | "preview_pending"
        - submission_id: int
        - error: str | None
    """
    config = get_config()

    # 1. Load booking with property
    booking = db.get(Booking, booking_id)
    if booking is None:
        return {"action": "error", "error": f"Booking {booking_id} not found"}

    prop = db.get(Property, booking.property_id)
    if prop is None:
        return {"action": "error", "error": f"Property {booking.property_id} not found"}

    # Find matching PropertyConfig for this property slug
    prop_config = None
    for pc in config.properties:
        if pc.slug == prop.slug:
            prop_config = pc
            break

    if prop_config is None:
        return {"action": "error", "error": f"No config for property slug '{prop.slug}'"}

    # 2. Check for existing submission (idempotent)
    existing = db.execute(
        select(ResortSubmission).where(ResortSubmission.booking_id == booking_id)
    ).scalar_one_or_none()

    if existing is not None:
        if existing.status in ("submitted", "confirmed"):
            return {
                "action": "already_exists",
                "submission_id": existing.id,
                "status": existing.status,
            }
        # If pending (from preview mode or prior failure), allow re-processing
        submission = existing
    else:
        # Create new submission record
        submission = ResortSubmission(booking_id=booking_id)
        db.add(submission)
        db.flush()  # Get the ID without committing

    # 3. Check preview mode
    auto_submit = should_auto_submit(db, config.auto_submit_threshold)

    if not auto_submit and existing is None:
        # Preview mode -- create as pending, don't send
        submission.submitted_automatically = False
        db.commit()
        log.info(
            "Submission created in preview mode (manual approval required)",
            booking_id=booking_id,
            submission_id=submission.id,
        )
        return {
            "action": "preview_pending",
            "submission_id": submission.id,
            "message": "Preview mode -- manual approval required before sending",
        }

    # 4. Fill PDF form
    # Split guest_name into first/last for the PDF fields (Text_2 / Text_3)
    name_parts = booking.guest_name.split(" ", 1)
    guest_first_name = name_parts[0]
    guest_last_name = name_parts[1] if len(name_parts) > 1 else ""

    booking_data = {
        "guest_first_name": guest_first_name,
        "guest_last_name": guest_last_name,
        "check_in_date": booking.check_in_date,
        "check_out_date": booking.check_out_date,
        "platform_booking_id": booking.platform_booking_id,
        "platform": booking.platform,
    }
    property_data = {
        "site_number": prop_config.site_number,
        "host_name": prop_config.host_name,
        "host_phone": prop_config.host_phone,
        "display_name": prop_config.display_name,
    }

    try:
        filled_pdf_bytes = fill_resort_form(
            template_pdf_path=config.pdf_template_path,
            mapping_json_path=config.pdf_mapping_path,
            booking_data=booking_data,
            property_data=property_data,
        )
    except (ValueError, FileNotFoundError) as exc:
        submission.error_message = f"PDF fill error: {exc}"
        db.commit()
        log.error("PDF fill failed", booking_id=booking_id, error=str(exc))
        return {
            "action": "failed",
            "submission_id": submission.id,
            "error": str(exc),
        }

    # 5. Find confirmation file (optional -- send without if not found)
    confirmation_bytes = None
    confirmation_filename = None
    conf_file = find_confirmation_file(
        booking.platform_booking_id,
        config.confirmations_dir,
    )
    if conf_file is not None:
        confirmation_bytes = conf_file.read_bytes()
        confirmation_filename = conf_file.name
        submission.confirmation_attached = True

    # 6. Format email
    subject = format_email_subject(
        guest_name=booking.guest_name,
        lot_number=prop_config.site_number,
        check_in=booking.check_in_date,
        check_out=booking.check_out_date,
    )
    body = format_email_body(
        contact_name=config.resort_contact_name,
    )
    form_filename = (
        f"BookingForm_{booking.guest_name.replace(' ', '')}_{prop_config.site_number}.pdf"
    )

    # 7. Send email with retry
    # Note: send_with_retry() attaches confirmation as second attachment when
    # confirmation_bytes is not None; filename is embedded in the EmailMessage
    # by the emailer (uses a default name). The form_filename is informational here
    # but not currently passed to the emailer (emailer uses "booking_form.pdf").
    try:
        await send_with_retry(
            smtp_host=config.smtp_host,
            smtp_port=config.smtp_port,
            smtp_user=config.smtp_user,
            smtp_password=config.smtp_password,
            from_email=config.smtp_from_email,
            to_email=prop_config.resort_contact_email,
            subject=subject,
            body=body,
            form_bytes=filled_pdf_bytes,
            confirmation_bytes=confirmation_bytes,
        )
    except Exception as exc:
        submission.error_message = f"Email send failed after retries: {exc}"
        db.commit()
        log.error(
            "Email send failed after all retries",
            booking_id=booking_id,
            error=str(exc),
        )
        return {
            "action": "failed",
            "submission_id": submission.id,
            "error": str(exc),
        }

    # 8. Update submission record on success
    submission.status = "submitted"
    submission.submitted_automatically = auto_submit
    submission.email_sent_at = datetime.now(timezone.utc)
    submission.error_message = None  # Clear any prior error
    db.commit()

    log.info(
        "Resort form submitted",
        booking_id=booking_id,
        submission_id=submission.id,
        guest=booking.guest_name,
        lot=prop_config.site_number,
        confirmation_attached=submission.confirmation_attached,
    )

    return {
        "action": "submitted",
        "submission_id": submission.id,
        "confirmation_attached": submission.confirmation_attached,
    }
