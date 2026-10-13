# Housework stabilization design

The user approved the stabilization scope from the 13 October audit with “Ok go”. This change fixes the existing integration rather than introducing new product features.

Keep the current config-subentry architecture and storage format. Repair service targeting before mutating state: validate Housework entities through the entity registry, resolve complete unique IDs, deduplicate task IDs, and reject explicitly invalid targets before processing a batch. Use Home Assistant's current service helper API. Share completion behavior between the service and button to prevent divergent fixes.

Calculate completion dates in the configured HA timezone. Completing or skipping a recurring occurrence must leave the next occurrence strictly in the future while preserving fixed cadence. Scheduling intervals must be positive. A completed or skipped one-time task must stay inactive during unrelated reconfiguration, unless explicitly reopened or converted to a recurring frequency.

Calendar queries must respect exact datetime bounds with an exclusive end, expand the entire requested interval, and order all-day events in HA local time. Form defaults must use integration options; diagnostics must redact person identifiers used as dictionary keys as well as values.

Preserve state across unload/reload by flushing pending runtime changes before a replacement store loads them. Test the suspected race against Home Assistant's actual storage and config-entry lifecycle before selecting the smallest fix. Do not require users of the current subentry format to delete and re-add their integration.

Add a reproducible Python development environment, real Home Assistant fixtures, regression tests and CI. Pin the HA fixture package used for verification, and choose the minimum supported HA release from the APIs actually used and the test matrix. Prepare documentation and a corrected version; do not install onto the user's running HA instance as part of local implementation.

Alternative approaches considered: replacing the integration architecture would add unnecessary migration work; a compatibility layer spanning untested old HA versions would increase complexity. Targeted fixes within the current architecture with an explicitly tested minimum provide the smallest reviewable change.

Success means all reported defects have regression coverage, actual config-entry/service/entity paths work in the selected HA environment, storage survives reload, and the full suite and lint pass. A final independent review checks scope and code quality before finishing the branch.
