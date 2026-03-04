"""Unit tests for Jinja2 guest message template rendering.

Tests load REAL templates from disk (templates/messages/welcome.j2 and
pre_arrival.j2) via render_message_template(). No mocking of template
loading — verifies actual file content renders correctly.

Design:
  - make_template_data() builds the same data dict shape that
    render_guest_message() would construct from a Booking + PropertyConfig.
  - render_message_template() is called with templates_dir pointing at the
    project's real templates/ directory (not cwd).
  - Conditional Jinja2 blocks in pre_arrival.j2 are tested for both
    presence and absence of optional sections.
"""

from __future__ import annotations

import pytest
import jinja2

from conftest import PROJECT_ROOT
from app.templates import render_message_template


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TEMPLATES_DIR = str(PROJECT_ROOT / "templates")


def make_template_data(
    guest_name: str = "Alice Chen",
    property_name: str = "Jay",
    checkin_date: str = "July 10, 2026",
    checkout_date: str = "July 15, 2026",
    lock_code: str = "1234",
    site_number: str = "110",
    resort_checkin_instructions: str = "Check in at the Welcome Center upon arrival.",
    wifi_password: str = "TestWifi123",
    address: str = "123 Test Resort Way, Fort Myers Beach, FL 33931",
    check_in_time: str = "4:00 PM",
    check_out_time: str = "11:00 AM",
    parking_instructions: str = "Park in the designated spot for your unit.",
    local_tips: str = "Nearest grocery: Publix (0.5 mi).",
    custom: dict | None = None,
    platform: str = "airbnb",
) -> dict:
    """Build the data dict matching what render_guest_message() constructs."""
    return {
        "guest_name": guest_name,
        "property_name": property_name,
        "checkin_date": checkin_date,
        "checkout_date": checkout_date,
        "lock_code": lock_code,
        "site_number": site_number,
        "resort_checkin_instructions": resort_checkin_instructions,
        "wifi_password": wifi_password,
        "address": address,
        "check_in_time": check_in_time,
        "check_out_time": check_out_time,
        "parking_instructions": parking_instructions,
        "local_tips": local_tips,
        "custom": custom or {},
        "platform": platform,
    }


def render_welcome(data: dict) -> str:
    return render_message_template("welcome.j2", data, templates_dir=TEMPLATES_DIR)


def render_pre_arrival(data: dict) -> str:
    return render_message_template("pre_arrival.j2", data, templates_dir=TEMPLATES_DIR)


# ---------------------------------------------------------------------------
# Welcome template tests
# ---------------------------------------------------------------------------


def test_welcome_renders_guest_name():
    result = render_welcome(make_template_data(guest_name="Alice Chen"))
    assert "Alice Chen" in result


def test_welcome_renders_property_name():
    result = render_welcome(make_template_data(property_name="Jay"))
    assert "Jay" in result


def test_welcome_renders_dates():
    result = render_welcome(
        make_template_data(checkin_date="July 10, 2026", checkout_date="July 15, 2026")
    )
    assert "July 10, 2026" in result
    assert "July 15, 2026" in result


def test_welcome_does_not_contain_lock_code():
    """Welcome template should NOT reveal the lock code — sent only in pre-arrival."""
    result = render_welcome(make_template_data(lock_code="SECRET9999"))
    assert "SECRET9999" not in result


@pytest.mark.parametrize(
    "platform, guest_name",
    [
        ("airbnb", "Alice Airbnb"),
        ("vrbo", "Victor VRBO"),
        ("rvshare", "Rachel RVshare"),
    ],
)
def test_welcome_multi_platform(platform: str, guest_name: str):
    """Welcome template renders correctly regardless of platform value."""
    result = render_welcome(make_template_data(platform=platform, guest_name=guest_name))
    assert guest_name in result


# ---------------------------------------------------------------------------
# Pre-arrival template tests
# ---------------------------------------------------------------------------


def test_pre_arrival_renders_lock_code():
    result = render_pre_arrival(make_template_data(lock_code="5678"))
    assert "5678" in result


def test_pre_arrival_renders_site_number():
    result = render_pre_arrival(make_template_data(site_number="170"))
    assert "170" in result


def test_pre_arrival_renders_address():
    result = render_pre_arrival(make_template_data(address="456 Beach Blvd, FL 33931"))
    assert "456 Beach Blvd, FL 33931" in result


def test_pre_arrival_renders_wifi_password():
    result = render_pre_arrival(make_template_data(wifi_password="BeachWifi2026"))
    assert "BeachWifi2026" in result


def test_pre_arrival_renders_check_times():
    result = render_pre_arrival(
        make_template_data(check_in_time="3:00 PM", check_out_time="10:00 AM")
    )
    assert "3:00 PM" in result
    assert "10:00 AM" in result


def test_pre_arrival_renders_parking_instructions():
    result = render_pre_arrival(
        make_template_data(parking_instructions="Park in Lot A, space 42")
    )
    assert "Park in Lot A, space 42" in result


def test_pre_arrival_hides_optional_sections_when_empty():
    """Jinja2 conditional blocks omit optional sections when values are empty."""
    result = render_pre_arrival(
        make_template_data(parking_instructions="", wifi_password="", local_tips="")
    )
    assert "PARKING" not in result
    assert "WIFI" not in result
    assert "LOCAL AREA TIPS" not in result


def test_pre_arrival_shows_optional_sections_when_present():
    """Jinja2 conditional blocks include optional sections when values are present."""
    result = render_pre_arrival(
        make_template_data(
            parking_instructions="Lot B",
            wifi_password="pass123",
            local_tips="Try Joe's Crab Shack",
        )
    )
    assert "PARKING" in result
    assert "WIFI" in result
    assert "LOCAL AREA TIPS" in result


def test_pre_arrival_renders_resort_checkin_instructions():
    result = render_pre_arrival(
        make_template_data(resort_checkin_instructions="Go to the main office, Building A")
    )
    assert "Go to the main office, Building A" in result


@pytest.mark.parametrize(
    "platform, guest_name, lock_code",
    [
        ("airbnb", "Alice Airbnb", "1111"),
        ("vrbo", "Victor VRBO", "2222"),
        ("rvshare", "Rachel RVshare", "3333"),
    ],
)
def test_pre_arrival_multi_platform(platform: str, guest_name: str, lock_code: str):
    """Pre-arrival template renders guest name and lock code on all platforms."""
    result = render_pre_arrival(
        make_template_data(platform=platform, guest_name=guest_name, lock_code=lock_code)
    )
    assert guest_name in result
    assert lock_code in result


# ---------------------------------------------------------------------------
# Error handling tests
# ---------------------------------------------------------------------------


def test_render_missing_template_raises():
    """Requesting a non-existent template raises TemplateNotFound."""
    with pytest.raises(jinja2.TemplateNotFound):
        render_message_template(
            "nonexistent.j2",
            make_template_data(),
            templates_dir=TEMPLATES_DIR,
        )


def test_render_missing_variable_raises():
    """Rendering with incomplete data raises UndefinedError (StrictUndefined)."""
    with pytest.raises(jinja2.UndefinedError):
        render_message_template(
            "welcome.j2",
            {"guest_name": "Alice"},  # missing many required variables
            templates_dir=TEMPLATES_DIR,
        )
