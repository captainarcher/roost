"""PDF fill verification script for PDFC-01 UAT.

Fills the production Sun Retreats booking form with test data, saves to
/tmp/verify_fill.pdf, prints field values, and opens the PDF in macOS Preview.

Run from project root:
    python scripts/verify_pdf_fill.py
"""

import subprocess
import sys

# Allow imports from project root when run as a script
sys.path.insert(0, ".")

from datetime import date

from pypdf import PdfReader

from app.compliance.pdf_filler import fill_resort_form

# ── Test data ─────────────────────────────────────────────────────────────────

TEMPLATE_PDF = "pdf_mappings/sun_retreats_booking.pdf"
MAPPING_JSON = "pdf_mappings/sun_retreats_booking.json"
OUTPUT_PATH = "/tmp/verify_fill.pdf"

BOOKING_DATA = {
    "guest_first_name": "John",
    "guest_last_name": "Smith",
    "check_in_date": date(2026, 4, 5),
    "check_out_date": date(2026, 4, 10),
    "platform_booking_id": "TEST-VERIFY-001",
    "platform": "airbnb",
}

PROPERTY_DATA = {
    "site_number": "110",
    "host_name": "Thomas",
    "host_phone": "555-0110",
    "display_name": "Jay",
}

# ── Fill form ──────────────────────────────────────────────────────────────────

print("Filling PDF form...")
pdf_bytes = fill_resort_form(
    template_pdf_path=TEMPLATE_PDF,
    mapping_json_path=MAPPING_JSON,
    booking_data=BOOKING_DATA,
    property_data=PROPERTY_DATA,
)

# Write to /tmp
with open(OUTPUT_PATH, "wb") as f:
    f.write(pdf_bytes)

file_size = len(pdf_bytes)
print(f"\nOutput written: {OUTPUT_PATH}")
print(f"File size:      {file_size:,} bytes")

# ── Verify filled field values by reading back the PDF ─────────────────────────

print("\nField values in filled PDF:")
print("-" * 50)

reader = PdfReader(OUTPUT_PATH)
fields_found = 0

for page_num, page in enumerate(reader.pages):
    annots = page.get("/Annots", [])
    if not annots:
        continue
    for annot_ref in annots:
        try:
            annot = annot_ref.get_object() if hasattr(annot_ref, "get_object") else annot_ref
            if annot.get("/Subtype") != "/Widget":
                continue
            field_name = annot.get("/T")
            if field_name is None:
                continue
            value = annot.get("/V", "")
            if hasattr(value, "get_object"):
                value = value.get_object()
            value_str = str(value) if value else "(empty)"
            print(f"  {str(field_name):<15} = {value_str}")
            fields_found += 1
        except Exception:
            pass

print("-" * 50)
print(f"Fields found:   {fields_found}")

# ── Summary ────────────────────────────────────────────────────────────────────

print(f"\nSummary:")
print(f"  Template:  {TEMPLATE_PDF}")
print(f"  Mapping:   {MAPPING_JSON}")
print(f"  Output:    {OUTPUT_PATH}")
print(f"  Size:      {file_size:,} bytes")
print(f"  Fields:    {fields_found}")

# ── Open in macOS Preview ──────────────────────────────────────────────────────

print(f"\nOpening {OUTPUT_PATH} in macOS Preview...")
subprocess.run(["open", OUTPUT_PATH])

print("Done. Check macOS Preview to visually verify all fields are populated.")
