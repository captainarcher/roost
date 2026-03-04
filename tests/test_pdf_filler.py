"""Unit tests for PDF form filling and form type detection.

Tests fill_resort_form(), detect_form_type(), and list_form_fields() against
the real production Sun Retreats PDF template.

Phase 18 regression tests are included:
  - 18-01a: Helvetica font override (no CIDFont crash)
  - 18-01b: Read-only field flags after fill
"""

from __future__ import annotations

import io
import json
from datetime import date
from pathlib import Path

import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import NameObject

from app.compliance.pdf_filler import detect_form_type, fill_resort_form, list_form_fields
from conftest import PROJECT_ROOT

# Paths to the production template and mapping (shared reference assets, not test fixtures)
TEMPLATE_PDF = str(PROJECT_ROOT / "pdf_mappings/sun_retreats_booking.pdf")
MAPPING_JSON = str(PROJECT_ROOT / "pdf_mappings/sun_retreats_booking.json")

# Standard booking data used across multiple tests
_STANDARD_BOOKING = {
    "guest_first_name": "Alice",
    "guest_last_name": "Chen",
    "check_in_date": date(2026, 7, 10),
    "check_out_date": date(2026, 7, 15),
}
_STANDARD_PROPERTY = {"site_number": "110"}


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _widget_annotations(pdf_bytes: bytes) -> list:
    """Return all Widget annotations from a PDF loaded from bytes."""
    reader = PdfReader(io.BytesIO(pdf_bytes))
    widgets = []
    for page in reader.pages:
        annots = page.get("/Annots", [])
        if not annots:
            continue
        for ref in annots:
            try:
                annot = ref.get_object() if hasattr(ref, "get_object") else ref
                if annot.get("/Subtype") == "/Widget":
                    widgets.append(annot)
            except Exception:
                pass
    return widgets


def _field_value(pdf_bytes: bytes, field_name: str) -> str | None:
    """Return the /V value of the first annotation with /T == field_name."""
    reader = PdfReader(io.BytesIO(pdf_bytes))
    for page in reader.pages:
        annots = page.get("/Annots", [])
        if not annots:
            continue
        for ref in annots:
            try:
                annot = ref.get_object() if hasattr(ref, "get_object") else ref
                t = annot.get("/T")
                if t is not None and str(t) == field_name:
                    v = annot.get("/V")
                    return str(v) if v is not None else ""
            except Exception:
                pass
    return None


# ---------------------------------------------------------------------------
# Test 1: detect_form_type — production template is AcroForm
# ---------------------------------------------------------------------------


def test_detect_form_type_acroform():
    result = detect_form_type(TEMPLATE_PDF)
    assert result == "acroform"


# ---------------------------------------------------------------------------
# Test 2: detect_form_type — blank PDF has no form
# ---------------------------------------------------------------------------


def test_detect_form_type_no_form(tmp_path):
    blank_pdf = tmp_path / "blank.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    with open(blank_pdf, "wb") as f:
        writer.write(f)

    result = detect_form_type(str(blank_pdf))
    assert result == "none"


# ---------------------------------------------------------------------------
# Test 3: fill_resort_form populates all 8 fields with correct values
# ---------------------------------------------------------------------------


def test_fill_resort_form_populates_all_fields():
    pdf_bytes = fill_resort_form(
        template_pdf_path=TEMPLATE_PDF,
        mapping_json_path=MAPPING_JSON,
        booking_data=_STANDARD_BOOKING,
        property_data=_STANDARD_PROPERTY,
    )

    expected = {
        "Text_1": "110",
        "Text_2": "Alice",
        "Text_3": "Chen",
        "Text_4": "N/A",
        "Text_5": "N/A",
        "Text_6": "07/10/2026",
        "Text_7": "07/15/2026",
        "Text_8": "2",
    }

    for field_name, expected_value in expected.items():
        actual = _field_value(pdf_bytes, field_name)
        assert actual == expected_value, (
            f"Field {field_name}: expected {expected_value!r}, got {actual!r}"
        )


# ---------------------------------------------------------------------------
# Test 4: fill_resort_form returns valid PDF bytes
# ---------------------------------------------------------------------------


def test_fill_resort_form_returns_bytes():
    result = fill_resort_form(
        template_pdf_path=TEMPLATE_PDF,
        mapping_json_path=MAPPING_JSON,
        booking_data=_STANDARD_BOOKING,
        property_data=_STANDARD_PROPERTY,
    )

    assert isinstance(result, bytes)
    assert len(result) > 0
    assert result[:4] == b"%PDF"


# ---------------------------------------------------------------------------
# Test 5 (REGRESSION 18-01a): Filled fields use /Helv, not /F3 CIDFont
# ---------------------------------------------------------------------------


def test_fill_uses_helvetica_not_cidfont():
    pdf_bytes = fill_resort_form(
        template_pdf_path=TEMPLATE_PDF,
        mapping_json_path=MAPPING_JSON,
        booking_data=_STANDARD_BOOKING,
        property_data=_STANDARD_PROPERTY,
    )

    reader = PdfReader(io.BytesIO(pdf_bytes))
    text_widgets_found = 0

    for page in reader.pages:
        annots = page.get("/Annots", [])
        if not annots:
            continue
        for ref in annots:
            try:
                annot = ref.get_object() if hasattr(ref, "get_object") else ref
                if (
                    annot.get("/Subtype") == "/Widget"
                    and annot.get("/FT") == "/Tx"
                ):
                    da = annot.get("/DA", "")
                    da_str = str(da)
                    assert "/Helv" in da_str, (
                        f"Widget /DA does not contain '/Helv': {da_str!r}"
                    )
                    assert "/F3" not in da_str, (
                        f"Widget /DA still contains '/F3' CIDFont: {da_str!r}"
                    )
                    text_widgets_found += 1
            except Exception:
                pass

    # Sanity check: we should have found at least one text widget
    assert text_widgets_found > 0, "No text widget annotations found in filled PDF"


# ---------------------------------------------------------------------------
# Test 6 (REGRESSION 18-01b): Filled fields are read-only (/Ff == 1)
# ---------------------------------------------------------------------------


def test_fill_sets_fields_readonly():
    pdf_bytes = fill_resort_form(
        template_pdf_path=TEMPLATE_PDF,
        mapping_json_path=MAPPING_JSON,
        booking_data=_STANDARD_BOOKING,
        property_data=_STANDARD_PROPERTY,
    )

    widgets = _widget_annotations(pdf_bytes)
    assert len(widgets) > 0, "No widget annotations found in filled PDF"

    for annot in widgets:
        ff = annot.get("/Ff")
        assert ff is not None, f"Widget missing /Ff flag: {annot}"
        # /Ff == 1 means read-only
        assert int(ff) == 1, f"Widget /Ff is {ff!r}, expected 1 (read-only)"


# ---------------------------------------------------------------------------
# Test 7: fill_resort_form raises ValueError for non-AcroForm PDFs
# ---------------------------------------------------------------------------


def test_fill_resort_form_invalid_form_type(tmp_path):
    # Create a blank PDF with no form fields
    blank_pdf = tmp_path / "blank.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    with open(blank_pdf, "wb") as f:
        writer.write(f)

    # Create a minimal mapping JSON
    mapping_json = tmp_path / "mapping.json"
    mapping_json.write_text(json.dumps({"fields": {"Text_1": {"source": "static", "value": "test"}}}))

    with pytest.raises(ValueError, match="not 'acroform'"):
        fill_resort_form(
            template_pdf_path=str(blank_pdf),
            mapping_json_path=str(mapping_json),
            booking_data=_STANDARD_BOOKING,
            property_data=_STANDARD_PROPERTY,
        )


# ---------------------------------------------------------------------------
# Test 8: fill_resort_form raises ValueError for empty mapping
# ---------------------------------------------------------------------------


def test_fill_resort_form_empty_mapping(tmp_path):
    # Use production template (valid AcroForm) but empty mapping
    empty_mapping = tmp_path / "empty_mapping.json"
    empty_mapping.write_text(json.dumps({"fields": {}}))

    with pytest.raises(ValueError, match="No fields defined"):
        fill_resort_form(
            template_pdf_path=TEMPLATE_PDF,
            mapping_json_path=str(empty_mapping),
            booking_data=_STANDARD_BOOKING,
            property_data=_STANDARD_PROPERTY,
        )


# ---------------------------------------------------------------------------
# Test 9: list_form_fields returns expected field structure
# ---------------------------------------------------------------------------


def test_list_form_fields_returns_expected_fields():
    fields = list_form_fields(TEMPLATE_PDF)

    # Should return exactly 8 fields
    assert len(fields) == 8, f"Expected 8 fields, got {len(fields)}: {[f['name'] for f in fields]}"

    # Each dict must have required keys
    for f in fields:
        assert "page" in f, f"Field dict missing 'page' key: {f}"
        assert "name" in f, f"Field dict missing 'name' key: {f}"
        assert "type" in f, f"Field dict missing 'type' key: {f}"
        assert "current_value" in f, f"Field dict missing 'current_value' key: {f}"

    # All expected field names must be present
    field_names = {f["name"] for f in fields}
    expected_names = {f"Text_{i}" for i in range(1, 9)}
    assert expected_names == field_names, (
        f"Field names mismatch. Expected: {expected_names}, Got: {field_names}"
    )


# ---------------------------------------------------------------------------
# Test 10 (PARAMETERIZED): fill works across Airbnb, VRBO, RVshare booking data
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "booking_data",
    [
        pytest.param(
            {
                "guest_first_name": "Alice",
                "guest_last_name": "Chen",
                "check_in_date": date(2026, 7, 10),
                "check_out_date": date(2026, 7, 15),
            },
            id="airbnb",
        ),
        pytest.param(
            {
                "guest_first_name": "Bob",
                "guest_last_name": "Johnson",
                "check_in_date": date(2026, 8, 1),
                "check_out_date": date(2026, 8, 5),
            },
            id="vrbo",
        ),
        pytest.param(
            {
                "guest_first_name": "Carol",
                "guest_last_name": "Davis",
                "check_in_date": date(2026, 9, 15),
                "check_out_date": date(2026, 9, 20),
            },
            id="rvshare",
        ),
    ],
)
def test_fill_resort_form_multi_platform(booking_data):
    result = fill_resort_form(
        template_pdf_path=TEMPLATE_PDF,
        mapping_json_path=MAPPING_JSON,
        booking_data=booking_data,
        property_data=_STANDARD_PROPERTY,
    )

    assert isinstance(result, bytes)
    assert len(result) > 0
    assert result[:4] == b"%PDF"


# ---------------------------------------------------------------------------
# Test 11: fill produces correct date formatting including cross-year dates
# ---------------------------------------------------------------------------


def test_fill_resort_form_date_formatting():
    pdf_bytes = fill_resort_form(
        template_pdf_path=TEMPLATE_PDF,
        mapping_json_path=MAPPING_JSON,
        booking_data={
            "guest_first_name": "Alice",
            "guest_last_name": "Chen",
            "check_in_date": date(2026, 12, 25),
            "check_out_date": date(2027, 1, 2),
        },
        property_data=_STANDARD_PROPERTY,
    )

    assert _field_value(pdf_bytes, "Text_6") == "12/25/2026"
    assert _field_value(pdf_bytes, "Text_7") == "01/02/2027"
