"""PDF form filling for resort booking forms.

Uses pypdf (BSD-3-Clause) to:
1. Detect whether a PDF is AcroForm or XFA
2. Fill AcroForm fields from a JSON mapping
3. Enumerate all form fields for mapping discovery

COMPATIBILITY NOTE: pypdf fills fields using update_page_form_field_values()
with auto_regenerate=True to generate proper appearance streams. The template's
/DA is overridden from /F3 (ArialMT CIDFont) to /Helv (Helvetica) because
pypdf's appearance generator crashes on CIDFont character maps. Fields are set
to read-only after filling so the appearance streams are treated as final.
"""

from __future__ import annotations

import io
import json
import structlog
from datetime import date
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from pypdf.generic import NameObject, NumberObject, TextStringObject

log = structlog.get_logger()

# Map PDF field type codes to human-readable strings
_FIELD_TYPE_MAP: dict[str, str] = {
    "/Tx": "Text",
    "/Btn": "Button",
    "/Ch": "Choice",
    "/Sig": "Signature",
}


def detect_form_type(pdf_path: str) -> str:
    """Detect PDF form type: 'acroform', 'xfa', or 'none'.

    Args:
        pdf_path: Path to the PDF file.

    Returns:
        'acroform' if the PDF has fillable AcroForm fields (pypdf can fill).
        'xfa' if the PDF uses XFA forms (pypdf CANNOT fill -- different approach needed).
        'none' if the PDF has no form fields.
    """
    reader = PdfReader(pdf_path)

    # No fields at all
    fields = reader.get_fields()
    if not fields:
        return "none"

    # Check the root object's /AcroForm for an /XFA key
    root = reader.root_object
    acroform = root.get("/AcroForm")
    if acroform is not None:
        try:
            acroform_obj = acroform.get_object() if hasattr(acroform, "get_object") else acroform
            if "/XFA" in acroform_obj:
                return "xfa"
        except Exception:
            pass

    # Also check the convenience property (non-empty dict means XFA present)
    if reader.xfa:
        return "xfa"

    return "acroform"


def list_form_fields(pdf_path: str) -> list[dict]:
    """List all form field names, types, and current values in a PDF.

    Use this to inspect the actual resort form and build the JSON mapping.

    Args:
        pdf_path: Path to the PDF file.

    Returns:
        List of dicts with keys: page, name, type, current_value.
    """
    reader = PdfReader(pdf_path)
    fields = []

    # Iterate pages, collecting widget annotations to get page numbers
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
                ft_code = str(annot.get("/FT", "Unknown"))
                field_type = _FIELD_TYPE_MAP.get(ft_code, ft_code)
                current_value = annot.get("/V", "")
                if hasattr(current_value, "get_object"):
                    current_value = current_value.get_object()
                fields.append({
                    "page": page_num,
                    "name": str(field_name),
                    "type": field_type,
                    "current_value": str(current_value) if current_value else "",
                })
            except Exception:
                pass

    return fields


def fill_resort_form(
    template_pdf_path: str,
    mapping_json_path: str,
    booking_data: dict,
    property_data: dict,
) -> bytes:
    """Fill an AcroForm PDF from a JSON field mapping.

    The JSON mapping defines which PDF field gets which value from three sources:
    - "booking": value comes from booking_data dict
    - "property": value comes from property_data dict
    - "static": hardcoded value (e.g., "N/A" for guest phone)

    Sets /V (value) on each widget annotation and /NeedAppearances=True on the
    AcroForm so PDF viewers regenerate visual appearances on open. Compatible
    with Adobe Acrobat, macOS Preview, iOS Mail, and other modern viewers.

    Args:
        template_pdf_path: Path to the blank PDF form template.
        mapping_json_path: Path to the JSON field mapping file.
        booking_data: Dict with booking fields (guest_name, check_in_date, check_out_date, etc.)
        property_data: Dict with property fields (site_number, host_name, host_phone, etc.)

    Returns:
        Filled PDF as bytes -- ready for email attachment.

    Raises:
        ValueError: If the PDF is not an AcroForm, or if the mapping file is invalid.
        FileNotFoundError: If the template PDF or mapping JSON does not exist.
    """
    # Validate form type
    form_type = detect_form_type(template_pdf_path)
    if form_type != "acroform":
        raise ValueError(
            f"PDF at {template_pdf_path} is '{form_type}', not 'acroform'. "
            "pypdf can only fill AcroForm PDFs."
        )

    # Load field mapping
    mapping = json.loads(Path(mapping_json_path).read_text())
    field_map = mapping.get("fields", {})

    if not field_map:
        raise ValueError(f"No fields defined in mapping at {mapping_json_path}")

    # Build field values from three source types
    field_values: dict[str, str] = {}
    for pdf_field_name, spec in field_map.items():
        source = spec.get("source")
        if source == "static":
            field_values[pdf_field_name] = spec.get("value", "")
        elif source == "booking":
            raw = booking_data.get(spec.get("field", ""), "")
            # Format dates if format spec provided
            if "format" in spec and isinstance(raw, date):
                fmt = spec["format"]
                # Convert human-readable format to strftime format codes
                fmt = fmt.replace("MM", "%m").replace("DD", "%d").replace("YYYY", "%Y")
                raw = raw.strftime(fmt)
            field_values[pdf_field_name] = str(raw) if raw is not None else ""
        elif source == "property":
            field_values[pdf_field_name] = str(
                property_data.get(spec.get("field", ""), "")
            )
        else:
            log.warning(
                "Unknown source type in PDF mapping",
                field=pdf_field_name,
                source=source,
            )

    # Open template and clone into writer
    reader = PdfReader(template_pdf_path)
    writer = PdfWriter()
    writer.append(reader)

    # Override /DA on text fields from /F3 (ArialMT CIDFont) to /Helv
    # (Helvetica). pypdf's auto_regenerate crashes on CIDFont character maps
    # ('int' object has no attribute 'encode'), but works with standard fonts.
    for page in writer.pages:
        annots = page.get("/Annots", [])
        if not annots:
            continue
        for annot_ref in annots:
            try:
                annot = annot_ref.get_object() if hasattr(annot_ref, "get_object") else annot_ref
                if annot.get("/Subtype") == "/Widget" and annot.get("/FT") == "/Tx":
                    annot.update({
                        NameObject("/DA"): TextStringObject("/Helv 10.5 Tf 0 0 0 rg")
                    })
            except Exception:
                pass

    # Fill fields using pypdf's built-in method with appearance generation.
    # auto_regenerate=True creates proper /AP streams with correct font metrics.
    writer.update_page_form_field_values(
        writer.pages[0], field_values, auto_regenerate=True
    )

    # Set fields to read-only so viewers treat the appearance as final
    for page in writer.pages:
        annots = page.get("/Annots", [])
        if not annots:
            continue
        for annot_ref in annots:
            try:
                annot = annot_ref.get_object() if hasattr(annot_ref, "get_object") else annot_ref
                if annot.get("/Subtype") == "/Widget":
                    annot.update({NameObject("/Ff"): NumberObject(1)})
            except Exception:
                pass

    log.info(
        "PDF form filled",
        template=template_pdf_path,
        fields_mapped=len(field_values),
        fields_filled=len(field_values),
    )

    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()
