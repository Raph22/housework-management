# Changelog

## 0.5.0 — Unreleased

Requires Home Assistant 2026.10.1 or newer, matching the version used by the
regression suite. Update v0.4.0 in place and restart HA; existing tasks and runtime
storage are preserved. Do not remove and recreate the integration to upgrade.

- Restore all task actions on Home Assistant 2026.10 with the current ServiceCall API.
- Resolve task targets through entity registry links, including next-due sensors.
- Process each task once for device, area, label and overlapping entity targets.
- Validate all targets and reassignment choices before modifying a batch.
- Ignore global Housework hub entities reached indirectly by task labels or areas.
- Advance schedules correctly when several skip actions run without a refresh between them.
- Reject invalid frequency intervals and blank task names.
- Share completion behavior between actions and buttons; preserve assignment rotation during rapid completions.
- Keep completed one-time tasks inactive until explicitly reopened.
- Calculate completion dates in the HA timezone and advance fixed schedules beyond today.
- Preserve monthly recurrence when fast-forwarding across shorter months.
- Honor exclusive calendar bounds and return all occurrences in the requested interval.
- Isolate invalid legacy recurrence settings in the calendar and validate schedule calculations before changing a batch.
- Apply configured defaults in new-task forms and preserve cleared due dates when editing.
- Redact person identifiers stored as diagnostic dictionary keys.
- Save pending runtime state before unload/reload so recent completions are retained.
- Add pinned development dependencies, regression tests and GitHub Actions checks.
