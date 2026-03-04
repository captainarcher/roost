"""Core ingestion pipeline: archive, validate, upsert, record ImportRun.

This module is the single pipeline through which all CSV imports flow.
Adapters produce canonical records; the normalizer writes them to the
database and archives the raw file.

Public functions:
    ingest_csv           — Airbnb, VRBO CSV uploads
    ingest_bank_csv      — Mercury bank transaction CSV uploads
    create_manual_booking — RVshare manual booking entry (no CSV)
"""

from __future__ import annotations

import io
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

import polars as pl
import structlog
from sqlalchemy import func, literal_column, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.communication.scheduler import compute_pre_arrival_send_time, schedule_pre_arrival_job
from app.config import get_config
from app.ingestion.schemas import BankTransactionRecord, BookingRecord, RVshareEntryRequest
from app.models.bank_transaction import BankTransaction
from app.models.booking import Booking
from app.models.communication_log import CommunicationLog
from app.models.import_run import ImportRun
from app.models.property import Property
from app.models.resort_submission import ResortSubmission

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

log = structlog.get_logger()


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def archive_file(raw_bytes: bytes, filename: str, platform: str, archive_dir: str) -> Path:
    """Archive raw CSV bytes to a timestamped path.

    Writes to ``{archive_dir}/{platform}/YYYY-MM-DD_HH-MM-SS_{filename}``.
    Creates the platform subdirectory if it does not exist.

    Args:
        raw_bytes:   Raw file bytes from the upload.
        filename:    Original filename from the upload.
        platform:    Platform identifier (e.g. "airbnb", "vrbo", "mercury").
        archive_dir: Root archive directory from AppConfig.

    Returns:
        Path to the archived file.
    """
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S")
    dest_dir = Path(archive_dir) / platform
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / f"{ts}_{filename}"
    dest_path.write_bytes(raw_bytes)
    return dest_path


# Property slug → id cache (populated lazily, reset never — properties don't change at runtime)
_property_id_cache: dict[str, int] = {}


def resolve_property_id(slug: str, db: "Session") -> int:
    """Resolve a property slug to its integer primary key.

    Results are cached in a module-level dict to avoid repeated queries.
    There are only 2 properties, so memory impact is negligible.

    Args:
        slug: Property slug (e.g. "jay", "minnie").
        db:   Active SQLAlchemy session.

    Returns:
        Integer property id.

    Raises:
        ValueError: If no property with the given slug exists.
    """
    if slug in _property_id_cache:
        return _property_id_cache[slug]

    row = db.execute(select(Property.id).where(Property.slug == slug)).fetchone()
    if row is None:
        raise ValueError(
            f"Property slug '{slug}' not found in the database. "
            "Ensure the property is seeded and listing_slug_map is correct."
        )
    _property_id_cache[slug] = row.id
    return row.id


def build_listing_lookup() -> dict[str, str]:
    """Build a flat mapping of listing identifier → property slug.

    Iterates all PropertyConfig entries from the loaded config and merges
    each property's ``listing_slug_map`` into a single dict.

    Returns:
        Dict mapping platform listing identifiers to property slugs.
        Example: {"Jay's Beach House": "jay", "12345678": "minnie"}
    """
    config = get_config()
    lookup: dict[str, str] = {}
    for prop in config.properties:
        lookup.update(prop.listing_slug_map)
    return lookup


def _create_resort_submissions(
    inserted_booking_ids: list[str],
    platform: str,
    db: "Session",
) -> None:
    """Create pending ResortSubmission records for newly imported bookings.

    Only creates for NEW bookings (inserts), not updates. Records are created
    with status='pending'. Whether they auto-submit (email sent immediately)
    or wait for manual approval depends on the preview mode threshold,
    which is evaluated by the upload API endpoint after this function returns.

    Args:
        inserted_booking_ids: Platform booking IDs of newly inserted bookings.
        platform: Platform identifier (airbnb, vrbo, rvshare).
        db: Active SQLAlchemy session.
    """
    # Look up actual DB IDs for the inserted bookings
    booking_rows = db.execute(
        select(Booking.id, Booking.platform_booking_id).where(
            Booking.platform == platform,
            Booking.platform_booking_id.in_(inserted_booking_ids),
        )
    ).all()

    created_count = 0
    for booking_id, platform_booking_id in booking_rows:
        # Check if submission already exists (idempotent)
        existing = db.execute(
            select(ResortSubmission.id).where(
                ResortSubmission.booking_id == booking_id
            )
        ).scalar_one_or_none()

        if existing is not None:
            continue

        submission = ResortSubmission(booking_id=booking_id)
        db.add(submission)
        created_count += 1

    if created_count > 0:
        db.commit()
        log.info(
            "Resort submissions created",
            count=created_count,
            platform=platform,
        )


def _create_communication_logs(
    inserted_booking_ids: list[str],
    platform: str,
    db: "Session",
) -> list[int]:
    """Create CommunicationLog records for newly imported bookings.

    Creates two entries per booking for Airbnb, one entry for VRBO/RVshare:
    1. Welcome message — 'native_configured' for Airbnb only (created here).
       VRBO/RVshare welcome is handled by prepare_welcome_message() in the
       API layer (which also fires the operator notification email).
    2. Pre-arrival message — 'pending' with scheduled_for computed from
       check_in_date. Created for all platforms.

    For all platforms, also registers the APScheduler pre-arrival job
    (sync-safe: schedule_pre_arrival_job calls scheduler.add_job which is
    thread-safe in APScheduler 3.x).

    Args:
        inserted_booking_ids: Platform booking IDs of newly inserted bookings.
        platform: Platform identifier (airbnb, vrbo, rvshare).
        db: Active SQLAlchemy session.

    Returns:
        List of booking DB IDs that need async welcome message handling
        (VRBO/RVshare only — Airbnb welcome is native_configured and created
        here; VRBO/RVshare welcome is created by prepare_welcome_message()).
    """
    # Look up actual DB IDs and check-in dates for inserted bookings
    booking_rows = db.execute(
        select(Booking.id, Booking.check_in_date, Booking.platform_booking_id).where(
            Booking.platform == platform,
            Booking.platform_booking_id.in_(inserted_booking_ids),
        )
    ).all()

    welcome_needs_async: list[int] = []  # VRBO/RVshare booking IDs needing welcome notification
    created_count = 0

    for booking_id, check_in_date, platform_booking_id in booking_rows:
        # Check if logs already exist (idempotent)
        existing_count = db.execute(
            select(func.count()).select_from(CommunicationLog).where(
                CommunicationLog.booking_id == booking_id,
            )
        ).scalar_one()

        if existing_count > 0:
            continue

        if platform == "airbnb":
            # Airbnb welcome: system tracks it as native_configured.
            # Airbnb's own scheduled messaging handles delivery automatically.
            db.add(CommunicationLog(
                booking_id=booking_id,
                message_type="welcome",
                platform=platform,
                status="native_configured",
            ))
        else:
            # VRBO/RVshare: welcome log created by prepare_welcome_message()
            # in the API layer (async — also sends operator notification email).
            # Return this booking ID for BackgroundTasks processing.
            welcome_needs_async.append(booking_id)

        # Pre-arrival message for all platforms
        scheduled_for = compute_pre_arrival_send_time(check_in_date)
        db.add(CommunicationLog(
            booking_id=booking_id,
            message_type="pre_arrival",
            platform=platform,
            status="pending",
            scheduled_for=scheduled_for,
        ))

        created_count += 1

        # Schedule APScheduler job for pre-arrival (all platforms)
        schedule_pre_arrival_job(booking_id, check_in_date)

    if created_count > 0:
        db.commit()
        log.info(
            "Communication logs created",
            count=created_count,
            platform=platform,
            welcome_async_count=len(welcome_needs_async),
        )

    return welcome_needs_async


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def ingest_csv(
    raw_bytes: bytes,
    filename: str,
    platform: str,
    adapter: object,
    db: "Session",
) -> dict:
    """Full ingestion pipeline for a CSV upload (Airbnb, VRBO).

    Pipeline order:
        read CSV → validate headers → validate rows → archive →
        upsert bookings → record ImportRun → return summary

    Nothing is written to the database if validation fails (headers or rows).
    The raw file is archived *before* any DB writes so failed imports still
    leave an audit trace.

    Args:
        raw_bytes: Raw CSV bytes from the upload.
        filename:  Original filename (used for archive path and ImportRun).
        platform:  Platform identifier string, e.g. "airbnb" or "vrbo".
        adapter:   Adapter module exposing ``validate_headers(df)`` and
                   ``parse(df) -> (list[BookingRecord], list[str])``.
        db:        Active SQLAlchemy session (from ``get_db()``).

    Returns:
        Dict with keys: platform, filename, inserted, updated, skipped,
        inserted_ids, updated_ids.

    Raises:
        ValueError: On header mismatch or row-level validation errors.
                    All row errors are collected and reported together.
    """
    config = get_config()

    # 1. Read CSV — all columns as Utf8; adapters handle type conversion
    df = pl.read_csv(
        io.BytesIO(raw_bytes),
        infer_schema_length=0,
        null_values=["", "N/A"],
        try_parse_dates=False,
    )

    # 2. Validate headers — fails immediately with a descriptive message
    adapter.validate_headers(df)  # type: ignore[attr-defined]

    # 3. Parse rows — collect ALL errors before failing (halt-and-report)
    records, errors = adapter.parse(df)  # type: ignore[attr-defined]
    if errors:
        raise ValueError("\n".join(errors))

    # 4. Resolve property_ids — validate all slugs before any DB write
    slug_errors: list[str] = []
    property_id_map: dict[str, int] = {}
    for record in records:
        if record.property_slug not in property_id_map:
            try:
                property_id_map[record.property_slug] = resolve_property_id(
                    record.property_slug, db
                )
            except ValueError as exc:
                slug_errors.append(str(exc))
    if slug_errors:
        raise ValueError("\n".join(slug_errors))

    # 5. Archive raw file BEFORE any DB writes
    archive_path = archive_file(raw_bytes, filename, platform, config.archive_dir)

    # 6. Upsert each booking record
    #
    # Pre-check which booking IDs already exist so we can reliably distinguish
    # INSERT from UPDATE after the upsert.  The previous xmax-based detection
    # was unreliable with psycopg3 + SQLAlchemy 2.0 on PostgreSQL 16.
    existing_booking_ids: set[str] = set(
        db.scalars(
            select(Booking.platform_booking_id).where(
                Booking.platform == platform,
                Booking.platform_booking_id.in_(
                    [r.platform_booking_id for r in records]
                ),
            )
        ).all()
    )

    inserted_ids: list[str] = []
    updated_ids: list[str] = []

    for record in records:
        values = {
            "platform": record.platform,
            "platform_booking_id": record.platform_booking_id,
            "property_id": property_id_map[record.property_slug],
            "guest_name": record.guest_name,
            "check_in_date": record.check_in_date,
            "check_out_date": record.check_out_date,
            "net_amount": record.net_amount,
            "raw_platform_data": record.raw_platform_data,
        }
        stmt = pg_insert(Booking).values(**values)
        stmt = stmt.on_conflict_do_update(
            index_elements=["platform", "platform_booking_id"],
            set_={
                "guest_name": stmt.excluded.guest_name,
                "check_in_date": stmt.excluded.check_in_date,
                "check_out_date": stmt.excluded.check_out_date,
                "net_amount": stmt.excluded.net_amount,
                "raw_platform_data": stmt.excluded.raw_platform_data,
                "updated_at": func.now(),  # ORM onupdate is not triggered by upserts
            },
        )
        db.execute(stmt)

        if record.platform_booking_id in existing_booking_ids:
            updated_ids.append(record.platform_booking_id)
        else:
            inserted_ids.append(record.platform_booking_id)

    db.commit()

    # 6b. Create resort submission records for newly inserted bookings
    if inserted_ids:
        _create_resort_submissions(inserted_ids, platform, db)

    # 6c. Create communication log records for newly inserted bookings
    welcome_async_ids: list[int] = []
    if inserted_ids:
        welcome_async_ids = _create_communication_logs(inserted_ids, platform, db)

    # Look up actual DB IDs for inserted bookings (needed for background submission tasks)
    inserted_db_ids: list[int] = []
    if inserted_ids:
        rows = db.execute(
            select(Booking.id).where(
                Booking.platform == platform,
                Booking.platform_booking_id.in_(inserted_ids),
            )
        ).all()
        inserted_db_ids = [row.id for row in rows]

    # 7. Record ImportRun
    run = ImportRun(
        platform=platform,
        filename=filename,
        archive_path=str(archive_path),
        inserted_count=len(inserted_ids),
        updated_count=len(updated_ids),
        skipped_count=0,
    )
    db.add(run)
    db.commit()

    return {
        "platform": platform,
        "filename": filename,
        "inserted": len(inserted_ids),
        "updated": len(updated_ids),
        "skipped": 0,
        "inserted_ids": inserted_ids,
        "updated_ids": updated_ids,
        "inserted_db_ids": inserted_db_ids,
        "welcome_async_ids": welcome_async_ids,
    }


def ingest_bank_csv(
    raw_bytes: bytes,
    filename: str,
    adapter: object,
    db: "Session",
) -> dict:
    """Full ingestion pipeline for a Mercury bank transaction CSV.

    Pipeline order:
        read CSV → validate headers → validate rows → archive →
        upsert bank transactions → record ImportRun → return summary

    Nothing is written to the database if validation fails. The raw file
    is archived before any DB writes.

    Args:
        raw_bytes: Raw CSV bytes from the upload.
        filename:  Original filename (used for archive path and ImportRun).
        adapter:   Adapter module exposing ``validate_headers(df)`` and
                   ``parse(df) -> (list[BankTransactionRecord], list[str])``.
        db:        Active SQLAlchemy session (from ``get_db()``).

    Returns:
        Dict with keys: platform, filename, inserted, updated, skipped,
        inserted_ids, updated_ids.

    Raises:
        ValueError: On header mismatch or row-level validation errors.
    """
    config = get_config()
    platform = "mercury"

    # 1. Read CSV — all columns as Utf8
    df = pl.read_csv(
        io.BytesIO(raw_bytes),
        infer_schema_length=0,
        null_values=["", "N/A"],
        try_parse_dates=False,
    )

    # 2. Validate headers
    adapter.validate_headers(df)  # type: ignore[attr-defined]

    # 3. Parse rows — collect ALL errors before failing
    records, errors = adapter.parse(df)  # type: ignore[attr-defined]
    if errors:
        raise ValueError("\n".join(errors))

    # 4. Archive raw file BEFORE any DB writes
    archive_path = archive_file(raw_bytes, filename, platform, config.archive_dir)

    # 5. Upsert each bank transaction record
    inserted_ids: list[str] = []
    updated_ids: list[str] = []

    for record in records:
        values = {
            "transaction_id": record.transaction_id,
            "date": record.date,
            "description": record.description,
            "amount": record.amount,
            "raw_platform_data": record.raw_platform_data,
        }
        stmt = pg_insert(BankTransaction).values(**values)
        stmt = stmt.on_conflict_do_update(
            index_elements=["transaction_id"],
            set_={
                "date": stmt.excluded.date,
                "description": stmt.excluded.description,
                "amount": stmt.excluded.amount,
                "raw_platform_data": stmt.excluded.raw_platform_data,
                "updated_at": func.now(),  # ORM onupdate is not triggered by upserts
            },
        ).returning(literal_column("xmax"))

        row = db.execute(stmt).fetchone()
        if row is not None and row.xmax == 0:
            inserted_ids.append(record.transaction_id)
        else:
            updated_ids.append(record.transaction_id)

    db.commit()

    # 6. Record ImportRun
    run = ImportRun(
        platform=platform,
        filename=filename,
        archive_path=str(archive_path),
        inserted_count=len(inserted_ids),
        updated_count=len(updated_ids),
        skipped_count=0,
    )
    db.add(run)
    db.commit()

    return {
        "platform": platform,
        "filename": filename,
        "inserted": len(inserted_ids),
        "updated": len(updated_ids),
        "skipped": 0,
        "inserted_ids": inserted_ids,
        "updated_ids": updated_ids,
    }


def create_manual_booking(entry: RVshareEntryRequest, db: "Session") -> dict:
    """Create or update a manual RVshare booking entry (no CSV involved).

    Resolves the property slug to a property_id, upserts a Booking record,
    and records an ImportRun.

    Args:
        entry: Validated RVshareEntryRequest with all booking fields.
        db:    Active SQLAlchemy session (from ``get_db()``).

    Returns:
        Dict with keys: platform, filename, inserted, updated, skipped,
        inserted_ids, updated_ids.

    Raises:
        ValueError: If the property slug is not found in the database.
    """
    platform = "rvshare"

    # Resolve property slug to id — raises ValueError if not found
    property_id = resolve_property_id(entry.property_slug, db)

    values = {
        "platform": platform,
        "platform_booking_id": entry.confirmation_code,
        "property_id": property_id,
        "guest_name": entry.guest_name,
        "check_in_date": entry.check_in_date,
        "check_out_date": entry.check_out_date,
        "net_amount": entry.net_amount,
        "raw_platform_data": {"notes": entry.notes} if entry.notes else None,
    }
    stmt = pg_insert(Booking).values(**values)
    stmt = stmt.on_conflict_do_update(
        index_elements=["platform", "platform_booking_id"],
        set_={
            "guest_name": stmt.excluded.guest_name,
            "check_in_date": stmt.excluded.check_in_date,
            "check_out_date": stmt.excluded.check_out_date,
            "net_amount": stmt.excluded.net_amount,
            "raw_platform_data": stmt.excluded.raw_platform_data,
            "updated_at": func.now(),
        },
    ).returning(literal_column("xmax"))

    row = db.execute(stmt).fetchone()
    db.commit()

    inserted_ids: list[str] = []
    updated_ids: list[str] = []
    if row is not None and row.xmax == 0:
        inserted_ids.append(entry.confirmation_code)
    else:
        updated_ids.append(entry.confirmation_code)

    # Trigger resort submission for new manual bookings
    if inserted_ids:
        _create_resort_submissions(inserted_ids, platform, db)

    # Create communication log records for new manual bookings
    welcome_async_ids: list[int] = []
    if inserted_ids:
        welcome_async_ids = _create_communication_logs(inserted_ids, platform, db)

    # Look up actual DB IDs for inserted bookings (needed for background submission tasks)
    inserted_db_ids: list[int] = []
    if inserted_ids:
        rows = db.execute(
            select(Booking.id).where(
                Booking.platform == platform,
                Booking.platform_booking_id.in_(inserted_ids),
            )
        ).all()
        inserted_db_ids = [row.id for row in rows]

    # Record ImportRun — archive_path is "N/A" for manual entries (no file)
    run = ImportRun(
        platform=platform,
        filename="manual_entry",
        archive_path="N/A",
        inserted_count=len(inserted_ids),
        updated_count=len(updated_ids),
        skipped_count=0,
    )
    db.add(run)
    db.commit()

    return {
        "platform": platform,
        "filename": "manual_entry",
        "inserted": len(inserted_ids),
        "updated": len(updated_ids),
        "skipped": 0,
        "inserted_ids": inserted_ids,
        "updated_ids": updated_ids,
        "inserted_db_ids": inserted_db_ids,
        "welcome_async_ids": welcome_async_ids,
    }
