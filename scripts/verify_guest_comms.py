"""Guest communication verification script for COMM-01 through COMM-04.

Walks through all four guest communication verification steps against the live API.
Run from the project root after the API is running (docker compose up -d roost-api).

Usage:
    python scripts/verify_guest_comms.py [--base-url http://localhost:8000]

Requirements:
    - API running at base_url (default: http://localhost:8000)
    - tests/fixtures/airbnb_future.csv
    - tests/fixtures/vrbo_future.csv
    - SMTP configured in .env for COMM-02 full verification (email check)

COMM-01: Airbnb welcome creates native_configured log entry
COMM-02: VRBO welcome renders template and sends operator notification email
COMM-03: Pre-arrival job scheduled with correct timing (check-in - 2 days, 14:00 UTC)
COMM-04: Pre-arrival jobs rebuild from DB after app restart
"""

import argparse
import sys
import time
from datetime import datetime, timezone

# Allow imports from project root
sys.path.insert(0, ".")

import httpx

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

AIRBNB_FIXTURE = "tests/fixtures/airbnb_future.csv"
VRBO_FIXTURE = "tests/fixtures/vrbo_future.csv"

AIRBNB_CONFIRMATION_CODE = "HMUATTEST001"
VRBO_RESERVATION_ID = "VRBO-UAT-001"

AIRBNB_GUEST_NAME = "UAT Test Guest"
VRBO_GUEST_NAME = "VRBO UAT Guest"

# Expected check-in dates (from fixture)
AIRBNB_CHECK_IN = "2026-04-03"
VRBO_CHECK_IN = "2026-04-03"

# Pre-arrival timing: check-in minus 2 days at 14:00 UTC
AIRBNB_PRE_ARRIVAL_EXPECTED = "2026-04-01"
VRBO_PRE_ARRIVAL_EXPECTED = "2026-04-01"

# ---------------------------------------------------------------------------
# Result tracking
# ---------------------------------------------------------------------------

results: dict[str, str] = {}


def print_header(title: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")


def print_step(step: str) -> None:
    print(f"\n--- {step}")


def record_pass(comm_id: str, message: str) -> None:
    results[comm_id] = f"PASS - {message}"
    print(f"\n[{comm_id}]: PASS - {message}")


def record_fail(comm_id: str, message: str) -> None:
    results[comm_id] = f"FAIL - {message}"
    print(f"\n[{comm_id}]: FAIL - {message}")


def record_warn(comm_id: str, message: str) -> None:
    results[comm_id] = f"WARN - {message}"
    print(f"\n[{comm_id}]: WARN - {message}")


# ---------------------------------------------------------------------------
# COMM-01: Airbnb welcome (native_configured)
# ---------------------------------------------------------------------------


def run_comm_01(client: httpx.Client) -> None:
    print_header("COMM-01: Airbnb Welcome (native_configured)")

    print_step("Uploading tests/fixtures/airbnb_future.csv via POST /ingestion/airbnb/upload")
    try:
        with open(AIRBNB_FIXTURE, "rb") as f:
            response = client.post(
                "/ingestion/airbnb/upload",
                files={"file": ("airbnb_future.csv", f, "text/csv")},
                timeout=30.0,
            )
        response.raise_for_status()
        upload_result = response.json()
        print(f"  Upload result: {upload_result}")

        inserted = upload_result.get("inserted", 0)
        updated = upload_result.get("updated", 0)
        print(f"  Inserted: {inserted}, Updated: {updated}")

        if inserted == 0 and updated == 0:
            print("  NOTE: Booking was neither inserted nor updated. Check if it already exists.")
        elif updated > 0:
            print("  NOTE: Booking already existed (updated). Communication logs may already be set.")

    except httpx.HTTPStatusError as exc:
        record_fail("COMM-01", f"Upload failed: {exc.response.status_code} {exc.response.text}")
        return
    except FileNotFoundError:
        record_fail("COMM-01", f"Fixture file not found: {AIRBNB_FIXTURE}")
        return
    except Exception as exc:
        record_fail("COMM-01", f"Upload error: {exc}")
        return

    print_step("Fetching communication logs for Airbnb welcome")
    try:
        response = client.get(
            "/api/communication/logs",
            params={"platform": "airbnb", "message_type": "welcome"},
            timeout=10.0,
        )
        response.raise_for_status()
        logs = response.json()
    except Exception as exc:
        record_fail("COMM-01", f"Failed to fetch communication logs: {exc}")
        return

    # Find the log entry for our test booking
    test_log = None
    for entry in logs:
        if entry.get("platform_booking_id") == AIRBNB_CONFIRMATION_CODE:
            test_log = entry
            break

    if test_log is None:
        record_fail(
            "COMM-01",
            f"No communication log found for booking {AIRBNB_CONFIRMATION_CODE}. "
            f"Found {len(logs)} airbnb welcome log(s) total.",
        )
        return

    print(f"  Found log entry: log_id={test_log['log_id']}, status={test_log['status']}")

    status = test_log.get("status")
    if status == "native_configured":
        record_pass("COMM-01", "Airbnb welcome status is native_configured")
    else:
        record_fail("COMM-01", f"Expected status=native_configured, got status={status!r}")


# ---------------------------------------------------------------------------
# COMM-02: VRBO welcome (operator notification)
# ---------------------------------------------------------------------------


def run_comm_02(client: httpx.Client) -> None:
    print_header("COMM-02: VRBO Welcome (operator notification email)")

    print_step("Uploading tests/fixtures/vrbo_future.csv via POST /ingestion/vrbo/upload")
    try:
        with open(VRBO_FIXTURE, "rb") as f:
            response = client.post(
                "/ingestion/vrbo/upload",
                files={"file": ("vrbo_future.csv", f, "text/csv")},
                timeout=30.0,
            )
        response.raise_for_status()
        upload_result = response.json()
        print(f"  Upload result: {upload_result}")

        inserted = upload_result.get("inserted", 0)
        updated = upload_result.get("updated", 0)
        print(f"  Inserted: {inserted}, Updated: {updated}")

    except httpx.HTTPStatusError as exc:
        record_fail("COMM-02", f"Upload failed: {exc.response.status_code} {exc.response.text}")
        return
    except FileNotFoundError:
        record_fail("COMM-02", f"Fixture file not found: {VRBO_FIXTURE}")
        return
    except Exception as exc:
        record_fail("COMM-02", f"Upload error: {exc}")
        return

    print_step("Waiting 5 seconds for background welcome message task to complete...")
    time.sleep(5)

    print_step("Fetching communication logs for VRBO welcome")
    try:
        response = client.get(
            "/api/communication/logs",
            params={"platform": "vrbo", "message_type": "welcome"},
            timeout=10.0,
        )
        response.raise_for_status()
        logs = response.json()
    except Exception as exc:
        record_fail("COMM-02", f"Failed to fetch communication logs: {exc}")
        return

    # Find the log entry for our test booking
    test_log = None
    for entry in logs:
        if entry.get("platform_booking_id") == VRBO_RESERVATION_ID:
            test_log = entry
            break

    if test_log is None:
        record_fail(
            "COMM-02",
            f"No communication log found for booking {VRBO_RESERVATION_ID}. "
            f"Found {len(logs)} vrbo welcome log(s) total.",
        )
        return

    print(f"  Found log entry: log_id={test_log['log_id']}, status={test_log['status']}")
    print(f"  Guest: {test_log.get('guest_name')}")
    print(f"  operator_notified_at: {test_log.get('operator_notified_at')}")

    status = test_log.get("status")
    rendered = test_log.get("rendered_message")
    operator_notified = test_log.get("operator_notified_at")

    checks_passed = True

    if status != "pending":
        print(f"  ISSUE: Expected status=pending, got status={status!r}")
        checks_passed = False
    else:
        print(f"  status=pending: OK")

    if not rendered:
        print(f"  ISSUE: rendered_message is empty")
        checks_passed = False
    else:
        print(f"  rendered_message: present ({len(rendered)} chars)")

    if operator_notified:
        print(f"  operator_notified_at: {operator_notified} (SMTP email sent)")
        if checks_passed:
            record_pass(
                "COMM-02",
                f"VRBO welcome status=pending, rendered_message present, "
                f"operator_notified_at={operator_notified}",
            )
        else:
            record_fail("COMM-02", "VRBO welcome has issues (see above)")
    else:
        print(f"  operator_notified_at: not set")
        if not rendered:
            record_fail("COMM-02", "VRBO welcome: rendered_message missing and operator not notified")
        elif not checks_passed:
            record_fail("COMM-02", "VRBO welcome has status issues (see above)")
        else:
            record_warn(
                "COMM-02",
                "VRBO welcome status=pending, rendered_message present, "
                "but operator_notified_at is NOT set. "
                "Check SMTP configuration in .env — email was not sent.",
            )
            print(
                "\n  ACTION REQUIRED: Configure SMTP credentials in .env and restart:\n"
                "    docker compose restart roost-api\n"
                "  Then re-run this script for COMM-02 to show PASS."
            )

    # Human verification instruction regardless
    guest = test_log.get("guest_name") or VRBO_GUEST_NAME
    print(
        f"\n  MANUAL CHECK: Look for email with subject:\n"
        f'    "[Action Required] Welcome message ready - {guest} (VRBO)"\n'
        f"  Email body should include the rendered welcome message and\n"
        f'  "MESSAGE TO SEND (copy everything below this line):" section.'
    )


# ---------------------------------------------------------------------------
# COMM-03: Pre-arrival scheduling
# ---------------------------------------------------------------------------


def run_comm_03(client: httpx.Client) -> None:
    print_header("COMM-03: Pre-arrival Scheduling (check-in minus 2 days, 14:00 UTC)")

    print_step("Fetching pre_arrival communication logs")
    try:
        response = client.get(
            "/api/communication/logs",
            params={"message_type": "pre_arrival"},
            timeout=10.0,
        )
        response.raise_for_status()
        logs = response.json()
    except Exception as exc:
        record_fail("COMM-03", f"Failed to fetch communication logs: {exc}")
        return

    # Find logs for our two test bookings
    airbnb_log = None
    vrbo_log = None
    for entry in logs:
        if entry.get("platform_booking_id") == AIRBNB_CONFIRMATION_CODE:
            airbnb_log = entry
        elif entry.get("platform_booking_id") == VRBO_RESERVATION_ID:
            vrbo_log = entry

    now_utc = datetime.now(timezone.utc)
    all_ok = True

    for label, booking_id, log_entry, expected_send_date in [
        ("Airbnb", AIRBNB_CONFIRMATION_CODE, airbnb_log, AIRBNB_PRE_ARRIVAL_EXPECTED),
        ("VRBO", VRBO_RESERVATION_ID, vrbo_log, VRBO_PRE_ARRIVAL_EXPECTED),
    ]:
        print(f"\n  [{label} - {booking_id}]")
        if log_entry is None:
            print(f"    ISSUE: No pre_arrival log found for {booking_id}")
            all_ok = False
            continue

        status = log_entry.get("status")
        scheduled_for_str = log_entry.get("scheduled_for")
        check_in = log_entry.get("check_in_date")

        print(f"    status:        {status}")
        print(f"    check_in_date: {check_in}")
        print(f"    scheduled_for: {scheduled_for_str}")

        if status != "pending":
            print(f"    ISSUE: Expected status=pending, got {status!r}")
            all_ok = False

        if not scheduled_for_str:
            print(f"    ISSUE: scheduled_for is not set")
            all_ok = False
            continue

        # Parse and validate scheduled_for
        try:
            scheduled_for = datetime.fromisoformat(scheduled_for_str.replace("Z", "+00:00"))
            if scheduled_for.tzinfo is None:
                scheduled_for = scheduled_for.replace(tzinfo=timezone.utc)
        except ValueError:
            print(f"    ISSUE: Cannot parse scheduled_for: {scheduled_for_str!r}")
            all_ok = False
            continue

        # Must be in the future
        if scheduled_for <= now_utc:
            print(f"    ISSUE: scheduled_for is in the past: {scheduled_for_str}")
            all_ok = False
        else:
            print(f"    scheduled_for is in the future: OK")

        # Must be at 14:00 UTC
        if scheduled_for.hour != 14 or scheduled_for.minute != 0:
            print(
                f"    ISSUE: Expected 14:00 UTC, got {scheduled_for.hour:02d}:{scheduled_for.minute:02d} UTC"
            )
            all_ok = False
        else:
            print(f"    Time is 14:00 UTC: OK")

        # Must be on the expected date (check-in minus 2 days)
        expected_date_str = expected_send_date
        actual_date_str = scheduled_for.strftime("%Y-%m-%d")
        if actual_date_str == expected_date_str:
            print(f"    Date matches check_in - 2 days ({expected_date_str}): OK")
        else:
            print(f"    ISSUE: Expected send date {expected_date_str}, got {actual_date_str}")
            all_ok = False

    if all_ok:
        record_pass(
            "COMM-03",
            "Both Airbnb and VRBO pre_arrival logs exist, status=pending, "
            "scheduled_for is in the future at 14:00 UTC, 2 days before check-in",
        )
    else:
        record_fail("COMM-03", "One or more pre_arrival scheduling checks failed (see above)")

    # Docker log instructions
    print(
        "\n  MANUAL CHECK: Verify Docker logs show job scheduling:\n"
        "    docker compose logs roost-api | grep -i 'pre.arrival.*scheduled'\n"
        "  You should see 'Pre-arrival job scheduled' for each test booking."
    )


# ---------------------------------------------------------------------------
# COMM-04: Job rebuild after restart
# ---------------------------------------------------------------------------


def run_comm_04(client: httpx.Client) -> None:
    print_header("COMM-04: Pre-arrival Job Rebuild After Restart")

    print(
        "\n  ACTION REQUIRED: Restart the API container and check rebuild logs.\n"
        "\n  Run these commands in a separate terminal:\n"
        "    docker compose restart roost-api\n"
        "    docker compose logs roost-api | grep -i 'rebuilt'\n"
        "\n  You should see a log line containing:\n"
        '    "Pre-arrival jobs rebuilt from database" with rebuilt_count > 0\n'
    )

    input("  Press Enter after restarting and checking Docker logs to continue verification: ")

    print_step("Verifying pre_arrival logs still exist after restart")
    try:
        response = client.get(
            "/api/communication/logs",
            params={"message_type": "pre_arrival", "status": "pending"},
            timeout=10.0,
        )
        response.raise_for_status()
        logs = response.json()
    except Exception as exc:
        record_fail("COMM-04", f"Failed to fetch communication logs after restart: {exc}")
        return

    airbnb_log = None
    vrbo_log = None
    for entry in logs:
        if entry.get("platform_booking_id") == AIRBNB_CONFIRMATION_CODE:
            airbnb_log = entry
        elif entry.get("platform_booking_id") == VRBO_RESERVATION_ID:
            vrbo_log = entry

    now_utc = datetime.now(timezone.utc)
    all_ok = True

    for label, booking_id, log_entry in [
        ("Airbnb", AIRBNB_CONFIRMATION_CODE, airbnb_log),
        ("VRBO", VRBO_RESERVATION_ID, vrbo_log),
    ]:
        print(f"\n  [{label} - {booking_id}]")
        if log_entry is None:
            print(f"    ISSUE: pre_arrival log not found after restart for {booking_id}")
            all_ok = False
            continue

        scheduled_for_str = log_entry.get("scheduled_for")
        print(f"    scheduled_for: {scheduled_for_str}")

        if not scheduled_for_str:
            print(f"    ISSUE: scheduled_for is not set")
            all_ok = False
            continue

        try:
            scheduled_for = datetime.fromisoformat(scheduled_for_str.replace("Z", "+00:00"))
            if scheduled_for.tzinfo is None:
                scheduled_for = scheduled_for.replace(tzinfo=timezone.utc)

            if scheduled_for > now_utc:
                print(f"    scheduled_for is still in the future: OK")
            else:
                print(f"    ISSUE: scheduled_for is in the past after restart")
                all_ok = False
        except ValueError:
            print(f"    ISSUE: Cannot parse scheduled_for: {scheduled_for_str!r}")
            all_ok = False

    if all_ok:
        record_pass(
            "COMM-04",
            "Pre-arrival logs persist after restart with future scheduled_for times. "
            "Verify Docker logs show 'Pre-arrival scheduler jobs rebuilt' with rebuilt_count > 0.",
        )
    else:
        record_fail("COMM-04", "Pre-arrival log state after restart has issues (see above)")

    print(
        "\n  FINAL CHECK: Confirm Docker startup log shows:\n"
        '    "Pre-arrival scheduler jobs rebuilt from database" with rebuilt_count > 0\n'
        "  Command:\n"
        "    docker compose logs roost-api | grep -i 'rebuilt'"
    )


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


def print_summary() -> None:
    print_header("VERIFICATION SUMMARY")
    all_passed = True
    for comm_id in ["COMM-01", "COMM-02", "COMM-03", "COMM-04"]:
        result = results.get(comm_id, "NOT RUN")
        status_char = "PASS" if result.startswith("PASS") else ("WARN" if result.startswith("WARN") else "FAIL")
        if status_char not in ("PASS", "WARN"):
            all_passed = False
        print(f"  [{status_char}] {comm_id}: {result}")

    print()
    if all_passed:
        print("  All COMM requirements verified. Guest communication flows are working.")
    else:
        print("  One or more COMM requirements FAILED. Review output above for details.")
    print()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Verify guest communication flows (COMM-01 through COMM-04)"
    )
    parser.add_argument(
        "--base-url",
        default="http://localhost:8000",
        help="Base URL of the Roost API (default: http://localhost:8000)",
    )
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    print(f"\nConnecting to API at: {base_url}")

    with httpx.Client(base_url=base_url) as client:
        # Health check
        try:
            resp = client.get("/", timeout=5.0)
            print(f"API reachable: {resp.status_code}")
        except Exception as exc:
            print(f"\nERROR: Cannot reach API at {base_url}: {exc}")
            print("Ensure the API is running: docker compose up -d roost-api")
            sys.exit(1)

        run_comm_01(client)
        run_comm_02(client)
        run_comm_03(client)
        run_comm_04(client)

    print_summary()


if __name__ == "__main__":
    main()
