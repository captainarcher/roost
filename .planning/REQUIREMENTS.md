# Requirements: Roost

**Defined:** 2026-03-03
**Core Value:** Automated end-to-end rental operations — from booking notification to accounting entry — with zero manual intervention after initial configuration.

## v1.2 Requirements

Requirements for automation verification and test coverage. Each maps to roadmap phases.

### PDF Compliance Verification

- [x] **PDFC-01**: PDF form fields render visibly in macOS Preview after pypdf fill
- [x] **PDFC-02**: PDF email sends successfully via SMTP with booking form and confirmation attached
- [x] **PDFC-03**: Preview mode correctly holds first N submissions for manual approval, then auto-submits

### Guest Communication Verification

- [x] **COMM-01**: Welcome message creates native_configured log for Airbnb bookings
- [x] **COMM-02**: Welcome message renders template and notifies operator for VRBO/RVshare bookings
- [x] **COMM-03**: Pre-arrival message schedules and fires 2 days before check-in with lock code and property details
- [x] **COMM-04**: Pre-arrival jobs rebuild correctly after app restart

### Test Coverage

- [ ] **TEST-01**: Test infrastructure set up (conftest.py, test database, fixtures, mocked SMTP)
- [ ] **TEST-02**: Unit tests for PDF form filling (fill_resort_form, detect_form_type, field mapping)
- [ ] **TEST-03**: Unit tests for email formatting (subject line, body, confirmation file matching)
- [ ] **TEST-04**: Unit tests for message rendering (welcome and pre-arrival Jinja2 templates)
- [ ] **TEST-05**: Integration test for PDF submission flow (booking → fill → email send)
- [ ] **TEST-06**: Integration test for communication flow (booking import → message creation → operator notification)

## Out of Scope

| Feature | Reason |
|---------|--------|
| iOS Mail PDF rendering test | Requires physical device, can't be automated |
| End-to-end test with real SMTP | Unit/integration tests with mocked SMTP sufficient |
| Airbnb native messaging verification | Platform-controlled, Roost only logs status |
| CI/CD pipeline | Test infrastructure only; CI is a future milestone |
| Frontend test coverage | Backend automation flows are the priority |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| PDFC-01 | Phase 18 | Complete |
| PDFC-02 | Phase 18 | Complete |
| PDFC-03 | Phase 18 | Complete |
| COMM-01 | Phase 18 | Complete |
| COMM-02 | Phase 18 | Complete |
| COMM-03 | Phase 18 | Complete |
| COMM-04 | Phase 18 | Complete |
| TEST-01 | Phase 19 | Pending |
| TEST-02 | Phase 19 | Pending |
| TEST-03 | Phase 19 | Pending |
| TEST-04 | Phase 19 | Pending |
| TEST-05 | Phase 20 | Pending |
| TEST-06 | Phase 20 | Pending |

**Coverage:**
- v1.2 requirements: 13 total
- Mapped to phases: 13
- Unmapped: 0

---
*Requirements defined: 2026-03-03*
*Traceability updated: 2026-03-04*
