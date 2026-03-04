---
phase: 18-manual-uat-and-bug-fixes
plan: 01
subsystem: compliance
tags: [pdf, pypdf, acroform, helvetica, macOS-preview, resort-form]

requires:
  - phase: 16-pdf-form-and-compliance-automation
    provides: pdf_filler.py, sun_retreats_booking.json, sun_retreats_booking.pdf
provides:
  - PDF fill verification script (PDFC-01)
  - Fixed PDF rendering in macOS Preview (Helvetica + auto_regenerate + read-only)
affects:
  - 18-02 (email submission depends on correct PDF fill)
  - 20-v1.2-release (UAT sign-off required)

tech-stack:
  added: []
  patterns:
    - "pypdf appearance generation: override /DA to /Helv before auto_regenerate=True"
    - "Read-only fields (/Ff=1) lock appearance streams as final"

key-files:
  created:
    - scripts/verify_pdf_fill.py
  modified:
    - app/compliance/pdf_filler.py

key-decisions:
  - "Switched from /NeedAppearances=True to pypdf auto_regenerate=True for reliable cross-viewer rendering"
  - "Override /DA from /F3 (ArialMT CIDFont) to /Helv (Helvetica) — pypdf crashes on CIDFont character maps"
  - "Set fields read-only after filling so viewers treat appearance streams as final"

completed: 2026-03-04
---

# Phase 18 Plan 01: PDF Fill Verification (PDFC-01) Summary

**Verified PDF form filling renders correctly in macOS Preview after fixing CIDFont incompatibility with pypdf**

## Performance

- **Tasks:** 1/1 auto task complete + human checkpoint verified
- **Files modified:** 2 (1 created, 1 modified)
- **Bug fixes:** 1 critical (PDF rendering)

## Accomplishments
- Created `scripts/verify_pdf_fill.py` — fills production Sun Retreats template with test data and opens in Preview
- Fixed PDF rendering: template uses ArialMT CIDFont (/F3) which pypdf's appearance generator can't handle
- Final approach: override /DA to /Helv, use `update_page_form_field_values(auto_regenerate=True)`, set fields read-only
- Human-verified: all 8 form fields render correctly in macOS Preview at proper size

## Task Commits

1. **Task 1: Create PDF fill verification script** — `df240a8` (feat)
2. **Bug fix: PDF rendering** — `14bbe05` (fix)

## Bug Fixed: PDF Text Rendering in macOS Preview

**Root cause:** Template PDF uses /F3 (ArialMT as CIDFont Type0/Identity-H). pypdf's `auto_regenerate` crashes with `'int' object has no attribute 'encode'` on CIDFont character maps. The original `/NeedAppearances=True` approach produced tiny/invisible text in macOS Preview.

**Fix:** Override `/DA` on all text widgets from `/F3` to `/Helv` (Helvetica) before calling pypdf's built-in `update_page_form_field_values(auto_regenerate=True)`. Then set `/Ff=1` (read-only) so viewers treat the generated appearance streams as final.

**Iterations:** 7 attempts before finding the working approach (documented in pdf_filler.py docstring).

## Deviations from Plan
- Major: pdf_filler.py required significant rework (not just verification) due to CIDFont incompatibility

---
*Phase: 18-manual-uat-and-bug-fixes*
*Completed: 2026-03-04*
