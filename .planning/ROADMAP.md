# Milestone v1.2: Automation Verification & Testing

**Status:** In Progress
**Phases:** 18-20
**Total Plans:** TBD

## Overview

Verify that all automation flows built in v1.0 (PDF compliance submission, guest welcome messages, pre-arrival scheduling) work correctly after the pypdf migration in v1.1, fix any bugs discovered, then build a test suite from scratch to prevent regressions. Manual verification comes first to discover real issues before codifying expectations in tests.

## Phases

- [x] **Phase 18: Manual UAT & Bug Fixes** - Verify all 4 automation flows work end-to-end, fix anything broken
- [ ] **Phase 19: Test Infrastructure & Unit Tests** - Set up pytest framework and write unit tests for each component
- [ ] **Phase 20: Integration Tests** - Test full automation flows end-to-end with mocked external services

## Phase Details

### Phase 18: Manual UAT & Bug Fixes
**Goal**: Every automation flow (PDF fill, PDF email, welcome message, pre-arrival message) runs correctly in the live application -- verified by a human triggering each flow
**Depends on**: Phase 17 (v1.1 complete)
**Requirements**: PDFC-01, PDFC-02, PDFC-03, COMM-01, COMM-02, COMM-03, COMM-04
**Success Criteria** (what must be TRUE):
  1. A filled PDF opened in macOS Preview shows all guest and booking fields visibly populated (not hidden behind appearance streams)
  2. The SMTP email flow sends a message with the filled PDF and booking confirmation attached to the resort contact address (verified in preview mode)
  3. Preview mode holds the first N submissions for manual approval, then subsequent submissions auto-send without intervention
  4. An Airbnb booking triggers a welcome message and the native_configured status is logged
  5. A VRBO/RVshare booking triggers an operator notification email containing the rendered welcome message text for copy-paste
  6. A booking with a check-in date 2+ days away creates a scheduled pre-arrival job that fires with the correct lock code and property details
  7. After an app restart, previously scheduled pre-arrival jobs are rebuilt and still fire at their scheduled times
**Plans**: 3 plans

Plans:
- [x] 18-01-PLAN.md — PDF form filling verification (PDFC-01): script fills production PDF template, human verifies in macOS Preview
- [x] 18-02-PLAN.md — PDF email submission and preview mode verification (PDFC-02, PDFC-03): full submission pipeline with preview mode lifecycle
- [x] 18-03-PLAN.md — Guest communication verification (COMM-01, COMM-02, COMM-03, COMM-04): welcome logging, operator notifications, pre-arrival scheduling, job rebuild

### Phase 19: Test Infrastructure & Unit Tests
**Goal**: A pytest test suite exists that validates each automation component in isolation -- any future code change that breaks PDF filling, email formatting, or message rendering is caught immediately
**Depends on**: Phase 18 (bugs must be fixed before writing tests that assert correct behavior)
**Requirements**: TEST-01, TEST-02, TEST-03, TEST-04
**Success Criteria** (what must be TRUE):
  1. `pytest` runs from the project root and discovers all tests with proper async support, database fixtures, and mocked SMTP
  2. PDF filling tests verify that fill_resort_form populates expected fields, detect_form_type identifies the correct form, and field mappings produce valid PDF output
  3. Email formatting tests verify subject lines, body content, and confirmation file matching logic produce correct output for known inputs
  4. Message rendering tests verify that welcome and pre-arrival Jinja2 templates render with expected property details, lock codes, and guest names
**Plans**: TBD

Plans:
- [ ] 19-01: Test infrastructure setup (conftest.py, fixtures, mocked services)
- [ ] 19-02: PDF and email unit tests (TEST-02, TEST-03)
- [ ] 19-03: Message rendering unit tests (TEST-04)

### Phase 20: Integration Tests
**Goal**: Full automation flows are tested end-to-end with mocked external services -- a booking import produces the correct PDF email and guest messages without touching real SMTP or platform APIs
**Depends on**: Phase 19 (unit tests validate components; integration tests compose them)
**Requirements**: TEST-05, TEST-06
**Success Criteria** (what must be TRUE):
  1. A test simulates a booking import and verifies the complete PDF submission flow: booking data in, filled PDF generated, email composed with attachments, SMTP send called with correct arguments
  2. A test simulates a booking import and verifies the complete communication flow: booking triggers welcome message creation, operator notification sent, pre-arrival job scheduled with correct timing and content
  3. All integration tests use mocked SMTP and mocked platform APIs -- no real external calls are made during test execution
**Plans**: TBD

Plans:
- [ ] 20-01: PDF submission flow integration test (TEST-05)
- [ ] 20-02: Communication flow integration test (TEST-06)

## Progress

**Execution Order:** 18 -> 19 -> 20

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 18. Manual UAT & Bug Fixes | v1.2 | 3/3 | Complete | 2026-03-04 |
| 19. Test Infrastructure & Unit Tests | v1.2 | 0/3 | Not started | - |
| 20. Integration Tests | v1.2 | 0/2 | Not started | - |
