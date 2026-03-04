"""Email submission verification script for PDFC-02 / PDFC-03 UAT.

Walks through the full preview mode lifecycle:
  1. Pre-flight checks (API health, bookings, submission state)
  2. Step 1: Trigger submission in preview mode (expect preview_pending)
  3. Step 2: Approve the pending submission (triggers email send)
  4. Step 3: Check auto-submit threshold progress
  5. Step 4: Verify auto-submit (if threshold reached)

Run from project root:
    python scripts/verify_email_submission.py
    python scripts/verify_email_submission.py <booking_id>

CRITICAL PREREQUISITE: SMTP must be configured in .env before running.
  Set: SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_FROM_EMAIL
  Then restart the container: docker compose restart roost-api
"""

import sys

# Allow imports from project root when run as a script
sys.path.insert(0, ".")

import json

import httpx

BASE_URL = "http://localhost:8000"
AUTO_SUBMIT_THRESHOLD = 3  # Default from config — matches AppConfig default


# ── Helpers ───────────────────────────────────────────────────────────────────


def header(title: str) -> None:
    """Print a section header with === separators."""
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")


def ok(msg: str) -> None:
    print(f"  [OK]  {msg}")


def warn(msg: str) -> None:
    print(f"  [WARN] {msg}")


def err(msg: str) -> None:
    print(f"  [FAIL] {msg}")


def info(msg: str) -> None:
    print(f"        {msg}")


def print_response(resp: httpx.Response) -> dict:
    """Print status + JSON body, return parsed dict."""
    data = {}
    try:
        data = resp.json()
        print(f"  Status: {resp.status_code}")
        print(f"  Body:   {json.dumps(data, indent=10, default=str)}")
    except Exception:
        print(f"  Status: {resp.status_code}")
        print(f"  Body:   {resp.text[:500]}")
    return data


def pause(prompt: str = "Press Enter to continue...") -> str:
    """Pause for human input and return what they typed."""
    try:
        return input(f"\n  >> {prompt} ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\nAborted.")
        sys.exit(1)


# ── Main verification flow ────────────────────────────────────────────────────


def main() -> None:
    # ── SMTP warning ─────────────────────────────────────────────────────────
    header("PDFC-02 / PDFC-03 Email Submission Verification")
    print("""
  CRITICAL PREREQUISITE — SMTP must be configured before running this script.
  If you have not already done so:

    1. Edit .env and set:
         SMTP_HOST=sandbox.smtp.mailtrap.io   (or smtp.gmail.com)
         SMTP_PORT=2525                        (or 587)
         SMTP_USER=<your username>
         SMTP_PASSWORD=<your password>
         SMTP_FROM_EMAIL=<your from address>

    2. Restart the container:
         docker compose restart roost-api

  If SMTP is already configured, continue.
    """)
    pause("Press Enter to proceed (or Ctrl+C to abort and configure SMTP first):")

    client = httpx.Client(base_url=BASE_URL, timeout=30.0)

    # ── Pre-flight: API health ────────────────────────────────────────────────
    header("PRE-FLIGHT: API Health Check")
    try:
        resp = client.get("/health")
        if resp.status_code == 200:
            health_data = resp.json()
            ok(f"API is running at http://localhost:8000 — status: {health_data.get('status', 'unknown')}")
            info(f"Database: {health_data.get('database', 'unknown')}")
            props = [p["slug"] for p in health_data.get("properties", [])]
            info(f"Properties loaded: {props}")
        else:
            err(f"API returned unexpected status: {resp.status_code}")
            sys.exit(1)
    except httpx.ConnectError:
        err("Cannot connect to http://localhost:8000")
        info("Make sure the API is running: docker compose up -d")
        sys.exit(1)

    # ── Pre-flight: List bookings ─────────────────────────────────────────────
    header("PRE-FLIGHT: Available Bookings")
    resp = client.get("/ingestion/bookings")
    if resp.status_code != 200:
        err(f"Failed to list bookings: {resp.status_code}")
        sys.exit(1)

    bookings = resp.json()
    if not bookings:
        err("No bookings found in database. Ingest some bookings first.")
        sys.exit(1)

    # Note: /ingestion/bookings does not expose DB IDs — use confirmation_code
    # and guest names to identify bookings. The compliance/submissions endpoint
    # exposes booking_id (DB primary key) for already-submitted bookings.
    print(f"\n  Found {len(bookings)} booking(s) in the database:\n")
    for b in bookings[:10]:  # Show first 10
        guest = b.get("guest_name", "?")
        checkin = b.get("check_in_date", "?")
        prop = b.get("property_slug", "?")
        code = b.get("confirmation_code", "?")
        print(f"    {guest:<25}  check-in: {checkin}  property: {prop}  code: {code}")

    if len(bookings) > 10:
        print(f"    ... and {len(bookings) - 10} more")

    # ── Pre-flight: Current submission state ──────────────────────────────────
    header("PRE-FLIGHT: Current Submission State")
    resp = client.get("/api/compliance/submissions")
    if resp.status_code != 200:
        err(f"Failed to list submissions: {resp.status_code}")
        sys.exit(1)

    submissions = resp.json()
    auto_submitted_count = sum(
        1 for s in submissions if s.get("submitted_automatically") is True
    )
    pending_submissions = [s for s in submissions if s.get("status") == "pending"]
    submitted_booking_ids = {s["booking_id"] for s in submissions}
    max_submitted_booking_id = max(submitted_booking_ids, default=0)

    print(f"\n  Total submissions:           {len(submissions)}")
    print(f"  Auto-submitted:              {auto_submitted_count} / {AUTO_SUBMIT_THRESHOLD} (threshold)")
    print(f"  Pending (awaiting approval): {len(pending_submissions)}")
    print(f"  Preview mode active:         {'Yes' if auto_submitted_count < AUTO_SUBMIT_THRESHOLD else 'No (auto-submit enabled)'}")

    if submitted_booking_ids:
        print(f"\n  Known booking IDs with submissions: {sorted(submitted_booking_ids)}")

    # ── Determine booking to use ──────────────────────────────────────────────
    # NOTE: /ingestion/bookings does not return DB IDs — booking IDs must come from:
    #   a) A CLI argument: python scripts/verify_email_submission.py <id>
    #   b) Probing: try IDs above the max known submission booking_id
    #   c) The compliance/submissions endpoint (already-submitted bookings)
    cli_booking_id = None
    if len(sys.argv) > 1:
        try:
            cli_booking_id = int(sys.argv[1])
        except ValueError:
            warn(f"Invalid booking_id argument '{sys.argv[1]}', ignoring.")

    # ── Step 1: Trigger submission ────────────────────────────────────────────
    header("STEP 1: Trigger Submission (expect: preview_pending or submitted)")

    if cli_booking_id:
        booking_id_to_use = cli_booking_id
        info(f"Using CLI-specified booking ID: {booking_id_to_use}")
    else:
        # Probe for a valid unsubmitted booking ID by trying IDs above the
        # highest known submission booking_id. /ingestion/bookings does not
        # expose DB IDs, so we use the submissions list as the source of truth:
        # any ID above max_submitted_booking_id is a candidate.
        probe_start = max_submitted_booking_id + 1
        booking_id_to_use = None
        for probe_id in range(probe_start, probe_start + 20):
            if probe_id not in submitted_booking_ids:
                booking_id_to_use = probe_id
                info(f"Probed first unsubmitted candidate: ID {booking_id_to_use}")
                break

        if booking_id_to_use is None:
            # All probed IDs are submitted; check if any pending ones can be re-submitted
            if pending_submissions:
                booking_id_to_use = pending_submissions[0]["booking_id"]
                warn(f"No unsubmitted bookings found in probe range. Using existing pending booking ID {booking_id_to_use}.")
            else:
                err("Could not find an unsubmitted booking ID automatically.")
                info("Pass a booking ID explicitly: python scripts/verify_email_submission.py <id>")
                info(f"Bookings with existing submissions: {sorted(submitted_booking_ids)}")
                info("Check the database or ingest new bookings to get fresh IDs.")
                sys.exit(1)

    print(f"\n  Posting to: POST /api/compliance/submit/{booking_id_to_use}")
    resp = client.post(f"/api/compliance/submit/{booking_id_to_use}")
    data = print_response(resp)

    action = data.get("action", "")

    if action == "preview_pending":
        ok("Preview mode working correctly — submission held for approval.")
        info(f"Submission ID: {data.get('submission_id')}")
    elif action == "submitted":
        warn("Submission auto-sent immediately (preview mode threshold already reached).")
        info("PDFC-03 preview gating cannot be verified fresh — threshold was already met.")
        info("Skip to Step 3 to verify the auto-submit count, and check your email for PDFC-02.")
        pause("Press Enter to skip to Step 3:")
        _step_3_threshold_check(client, auto_submitted_count)
        return
    elif action == "already_exists":
        warn(f"Booking {booking_id_to_use} already has a submission (status: {data.get('status')}).")
        info("Try running with a different booking_id: python scripts/verify_email_submission.py <id>")
        pause("Press Enter to continue to Step 2 (checking for any pending submissions):")
    elif action == "failed":
        err(f"Submission failed: {data.get('error')}")
        info("Check API logs for details: docker compose logs roost-api --tail 50")
        sys.exit(1)
    else:
        err(f"Unexpected action: {action}")
        sys.exit(1)

    # ── Step 2: Approve the pending submission ────────────────────────────────
    header("STEP 2: Approve Pending Submission (triggers email send)")

    resp = client.get("/api/compliance/submissions", params={"status": "pending"})
    pending = resp.json()

    if not pending:
        err("No pending submissions found. Check that Step 1 created a preview_pending submission.")
        sys.exit(1)

    print(f"\n  Found {len(pending)} pending submission(s):")
    for s in pending:
        print(f"    Submission ID {s['submission_id']}  |  Booking ID {s['booking_id']}  |  Guest: {s.get('guest_name', '?')}")

    # Use the first pending submission
    submission_id = pending[0]["submission_id"]
    print(f"\n  Approving submission ID {submission_id}...")
    print(f"  Posting to: POST /api/compliance/approve/{submission_id}")

    resp = client.post(f"/api/compliance/approve/{submission_id}")
    data = print_response(resp)

    approve_action = data.get("action", "")
    if approve_action == "submitted":
        ok("Approval succeeded — email should have been sent.")
    elif approve_action == "failed":
        err(f"Email send failed: {data.get('error')}")
        info("Check SMTP credentials in .env and restart: docker compose restart roost-api")
        info("Then check API logs: docker compose logs roost-api --tail 50")
        sys.exit(1)
    else:
        warn(f"Unexpected approval response: {approve_action}")

    print("""
  ┌─────────────────────────────────────────────────────────────────┐
  │  CHECK YOUR EMAIL INBOX NOW                                     │
  │                                                                 │
  │  You should receive an email with:                              │
  │    Subject: "Booking Form - {Guest} - Lot {N} - {dates}"        │
  │    Attachment: booking_form.pdf (filled resort form)            │
  │    Body: "Hi {contact}, Please find the attached booking form"  │
  │                                                                 │
  │  If using Mailtrap: check https://mailtrap.io/inboxes           │
  │  If using Gmail:    check sent mail / recipient inbox           │
  └─────────────────────────────────────────────────────────────────┘
    """)

    email_result = pause("Press Enter if email arrived (or type 'fail' if no email received):")
    if email_result.lower() == "fail":
        err("Email not received.")
        info("Troubleshooting:")
        info("  1. Check SMTP config in .env (SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD)")
        info("  2. Restart: docker compose restart roost-api")
        info("  3. Check logs: docker compose logs roost-api --tail 100")
        info("  4. If using Gmail, ensure you are using an App Password (not your account password)")
        sys.exit(1)
    else:
        ok("PDFC-02 VERIFIED: Email arrived with PDF attachment.")

    # ── Step 3: Check threshold ───────────────────────────────────────────────
    _step_3_threshold_check(client, None)


def _step_3_threshold_check(client: httpx.Client, prior_count: int | None) -> None:
    """Step 3: Check auto-submit threshold and optionally run Step 4."""
    header("STEP 3: Auto-Submit Threshold Status")

    resp = client.get("/api/compliance/submissions")
    submissions = resp.json()
    auto_count = sum(1 for s in submissions if s.get("submitted_automatically") is True)

    print(f"\n  Auto-submitted count:  {auto_count}")
    print(f"  Threshold:             {AUTO_SUBMIT_THRESHOLD}")
    print(f"  Preview mode active:   {'Yes — still gating new submissions' if auto_count < AUTO_SUBMIT_THRESHOLD else 'No — auto-submit is enabled'}")

    if auto_count < AUTO_SUBMIT_THRESHOLD:
        remaining = AUTO_SUBMIT_THRESHOLD - auto_count
        print(f"""
  Preview mode is still active. {remaining} more approved submission(s) needed to reach threshold.

  To continue verification:
    1. Run: python scripts/verify_email_submission.py <another_booking_id>
    2. Approve the resulting pending submission via Step 2
    3. Repeat until threshold ({AUTO_SUBMIT_THRESHOLD}) is reached

  Once reached, run this script again to verify auto-submit (Step 4).
        """)
        ok(f"PDFC-03 PARTIAL: Preview mode gating confirmed ({auto_count}/{AUTO_SUBMIT_THRESHOLD} threshold).")
        info("Complete Steps 1-2 with more bookings to fully verify auto-submit path.")
    else:
        ok(f"PDFC-03 VERIFIED: Threshold reached ({auto_count}/{AUTO_SUBMIT_THRESHOLD}). Auto-submit enabled.")
        _step_4_auto_submit(client, submissions)


def _step_4_auto_submit(client: httpx.Client, existing_submissions: list) -> None:
    """Step 4: Verify auto-submit works after threshold."""
    header("STEP 4: Verify Auto-Submit (threshold reached)")

    submitted_booking_ids = {s["booking_id"] for s in existing_submissions}
    max_submitted_booking_id = max(submitted_booking_ids, default=0)

    # Probe for a valid unsubmitted booking ID
    # /ingestion/bookings does not expose DB IDs, so we probe sequentially
    booking_id = None
    for probe_id in range(max_submitted_booking_id + 1, max_submitted_booking_id + 30):
        if probe_id not in submitted_booking_ids:
            booking_id = probe_id
            break

    if booking_id is None:
        warn("No unsubmitted bookings found in probe range for auto-submit test.")
        info("Ingest new bookings and re-run to test auto-submit.")
        info("PDFC-03 auto-submit path cannot be verified without a fresh booking.")
        return

    info(f"Using probed booking ID {booking_id}")

    print(f"\n  Posting to: POST /api/compliance/submit/{booking_id}")
    print("  Expecting action: submitted (not preview_pending)")

    resp = client.post(f"/api/compliance/submit/{booking_id}")
    data = print_response(resp)

    action = data.get("action", "")
    if action == "submitted":
        ok("PDFC-03 VERIFIED: Auto-submit triggered immediately (no approval needed).")
        info("Email should have been sent automatically — check your inbox.")
    elif action == "preview_pending":
        err("PDFC-03 FAIL: Got preview_pending after threshold should have been reached.")
        info("Check the auto_submit_threshold config and submitted_automatically counts in DB.")
    elif action == "failed":
        err(f"Submission failed: {data.get('error')}")
        info("Check API logs: docker compose logs roost-api --tail 50")
    else:
        warn(f"Unexpected action: {action}")

    # ── Final summary ─────────────────────────────────────────────────────────
    header("VERIFICATION COMPLETE")
    print("""
  Results:
    PDFC-02 (Email with PDF):   Check email inbox — booking_form.pdf attached?
    PDFC-03 (Preview mode):     Confirmed if:
                                  - Step 1 returned preview_pending
                                  - Step 2 approval triggered the email
                                  - After threshold: Step 4 returned submitted

  If both criteria are met, type "approved" in the orchestrator prompt.
    """)


if __name__ == "__main__":
    main()
