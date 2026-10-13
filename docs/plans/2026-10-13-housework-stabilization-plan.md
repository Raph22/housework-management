# Housework Stabilization Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix the defects documented by the 13 October audit and make the existing integration reproducibly testable on current Home Assistant.

**Architecture:** Preserve config subentries and the current runtime storage schema. Validate and deduplicate targets before updates, centralize completion, use HA timezone handling, and flush persistent state across lifecycle boundaries. Independent file groups can be implemented in parallel with test-first regression checks.

**Tech Stack:** Python 3.14, Home Assistant, pytest-homeassistant-custom-component, pytest, Ruff, GitHub Actions.

---

### Task 1: Reproducible test environment

Create `pyproject.toml`, `requirements-dev.txt`, `tests/conftest.py`, and `.github/workflows/ci.yaml`. Update `.gitignore` for local virtual environments and test artifacts. Pin the installed fixture package and Ruff versions. Configure pytest's automatic asyncio mode and project import path. Use real HA fixtures and custom-integration loading rather than AST extraction. Baseline `pytest` collected no tests; the audit's isolated probes established the existing failures.

Verification: `.venv/bin/python -m pytest -q`; `.venv/bin/ruff check custom_components tests`.

### Task 2: Service targeting, validation and shared completion

Files: `custom_components/housework/services.py`, `button.py`, optional `actions.py`; `tests/test_services.py`, `tests/test_button.py`.

Write failing tests for current helper API, `_next_due` resolution, device/area/label targeting, duplicate entity targets, invalid batch targets, removal batches, and zero/negative frequency rejection. Confirm the failures before editing production code. Change the helper call to accept only ServiceCall, verify registry integration ownership, deduplicate task IDs, validate batch targets before mutation and validate positive integral intervals. Extract shared completion logic so service and button use identical date/assignment/history handling. Verify one history/event and one schedule advance per task.

### Task 3: Scheduling and reconciliation

Files: `custom_components/housework/scheduling.py`, `coordinator.py`; `tests/test_scheduling.py`, `tests/test_coordinator.py`.

Write failing tests for Paris completions at local midnight, fixed late completions landing on today, one-time task completion/skip surviving schedule-mode reconfiguration, and progress safety for invalid intervals. Include monthly and selected-weekday controls, explicit reopening, and recurrence conversion. Convert completion timestamps with HA datetime helpers before extracting dates; fast-forward fixed completion strictly after the reference day. Keep inactive once tasks inactive unless reconfiguration intentionally changes recurrence or sets a new due date. Confirm initial-due and explicit-date precedence remain valid.

### Task 4: Calendar, form defaults and diagnostics

Files: `custom_components/housework/calendar.py`, `config_flow.py`, `diagnostics.py`; `tests/test_calendar.py`, `tests/test_config_flow.py`, `tests/test_diagnostics.py`.

Write failing tests for exclusive midnight end, non-midnight overlapping all-day events, annual daily projection (365 events), integration option defaults, completed-task form defaults, and person identifiers in completion-count keys. Respect local datetime interval overlap without a 52-event truncation. Seed new-task forms from entry options without overriding existing task settings. Ensure diagnostics redact keyed person data. Verify custom-integration flow and calendar behavior with real HA fixtures.

### Task 5: Storage lifecycle and integration behavior

Files: `custom_components/housework/store.py`, `__init__.py`; `tests/test_store.py`, `tests/test_integration.py`.

Reproduce delayed-save/reload behavior using actual HA Store and config-entry fixtures. Write a failing reload persistence test before selecting the fix. Persist pending runtime state at unload and manage timers/listeners consistently. Test empty startup, add task, per-task entities, button/service completion, priority edits, reconfigure, task removal, unload/reload and removal cleanup. Check future reload changes cannot overwrite saved completion data.

### Task 6: Verification, documentation and version preparation

Files: `README.md`, `hacs.json`, `custom_components/housework/manifest.json`, `CHANGELOG.md`, `LICENSE`.

Document supported HA and Python versions, exact test commands and upgrade preservation for the existing storage format. Prepare a corrected version with factual release notes. Add the MIT license already stated in the README. Run the full regression suite, Ruff and JSON checks. Obtain independent specification and quality review, resolve actionable findings, then run the final checks on the final diff. Keep the resulting changes reviewable in the original workspace; external publication is a separate finishing action.
