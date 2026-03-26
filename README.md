# Housework

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge)](https://github.com/hacs/integration)

A Home Assistant custom integration for managing household chores and recurring tasks.

Assign tasks to household members, track completions, and automate reminders — all from within Home Assistant using standard dashboard cards and automations.

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Raph22&repository=housework-management&category=integration)

[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=housework)

## Features

- **Recurring tasks** with flexible scheduling: daily, weekly, monthly, specific days of the week, or one-time
- **Rolling or fixed scheduling**: rolling adjusts to actual completion time; fixed keeps the original cadence
- **Person assignment** with rotation strategies: round robin, least completed, random, or fixed
- **Completion history** tracked in storage
- **Priority levels** (P1 urgent to P4 low)
- **Binary sensor per task** — turns on when due/overdue, works with any HA automation
- **Calendar entity** — view all chores on the HA calendar
- **Stats sensors** — "tasks due today" and "overdue tasks" counts for dashboard badges
- **8 services** for full task management from automations and scripts
- **Events** fired on complete, skip, and snooze for automation triggers
- **English and French** translations

## Installation

### HACS (recommended)

1. Add this repository as a custom repository in HACS
2. Install "Housework"
3. Restart Home Assistant
4. Go to **Settings > Integrations > Add Integration > Housework**

### Manual

1. Copy `custom_components/housework/` to your Home Assistant `config/custom_components/` directory
2. Restart Home Assistant
3. Go to **Settings > Integrations > Add Integration > Housework**

## Usage

### Creating tasks

Create tasks from the UI: **Settings > Integrations > Housework > Add task**. This opens a form with all configuration options.

You can also create tasks from automations or Developer Tools via services:

```yaml
service: housework.add_task
data:
  title: "Clean bathroom"
  frequency_type: weekly
  frequency_value: 2
  priority: 2
  assignees:
    - person.alice
    - person.bob
  assignment_strategy: round_robin
```

### Frequency types

| Type | Description | Example |
|------|-------------|---------|
| `daily` | Every N days | `frequency_value: 3` = every 3 days |
| `weekly` | Every N weeks | `frequency_value: 2` = biweekly |
| `monthly` | Every N months, optional day | `frequency_day_of_month: 15` = 15th of each month |
| `day_of_week` | Specific weekdays | `frequency_days_of_week: [0, 2, 4]` = Mon/Wed/Fri |
| `once` | One-time task | Set `next_due` for the target date |

### Scheduling modes

- **Rolling** (default): next due date is calculated from when the task was last completed. If you complete a biweekly task 3 days late, the next occurrence is 2 weeks from now.
- **Fixed**: next due date follows the original cadence. If a biweekly task was due Monday and you complete it Wednesday, the next is still the following Monday.

### Completing tasks

```yaml
service: housework.complete_task
target:
  entity_id: binary_sensor.housework_clean_bathroom
data:
  completed_by: person.alice
```

### Other services

| Service | Description |
|---------|-------------|
| `housework.add_task` | Create a new task |
| `housework.complete_task` | Mark task as done, advance schedule, rotate assignee |
| `housework.skip_task` | Skip current occurrence, advance to next |
| `housework.snooze_task` | Postpone to a specific date |
| `housework.reassign_task` | Change the current assignee |
| `housework.update_task` | Modify task properties (title, priority, icon, etc.) |
| `housework.remove_task` | Delete a task |
| `housework.reopen_task` | Set a new due date on a completed task |

## Entities

Each task is a **device** with 4 entities:

| Entity | Type | Description |
|--------|------|-------------|
| **Due** | Binary sensor | `on` when due or overdue, `off` when upcoming or completed |
| **Next due** | Date sensor | Shows the due date with native relative rendering ("in 3 days") |
| **Priority** | Select | P1-P4 dropdown, changeable directly from the dashboard |
| **Mark done** | Button | Press to complete the task, advance schedule, rotate assignee |

The binary sensor also exposes attributes for templates: `task_id`, `title`, `priority`, `next_due`, `last_completed`, `current_assignee`, `assignee_name`, `frequency`, `days_overdue`, `scheduling_mode`, `assignment_strategy`.

Use HA's native labels (Settings > Labels) to categorize tasks — assign labels to task devices or entities for targeting in automations.

### Global entities (Housework hub device)

- `calendar.housework` — all tasks as events, including projected future occurrences
- `sensor.housework_tasks_due_today` — count of tasks due today (with task list in attributes)
- `sensor.housework_overdue_tasks` — count of overdue tasks (with details in attributes)

## Events

Use these in automations to trigger notifications or other actions:

- `housework_task_completed` — `task_id`, `title`, `completed_by`, `next_due`
- `housework_task_skipped` — `task_id`, `title`, `next_due`
- `housework_task_snoozed` — `task_id`, `title`, `snooze_until`

## Automation examples

### Notify when a task is due

```yaml
automation:
  - alias: "Notify chore assignee"
    trigger:
      - platform: state
        entity_id: binary_sensor.housework_clean_bathroom
        to: "on"
    action:
      - service: notify.mobile_app
        data:
          title: "Chore due"
          message: >
            {{ state_attr('binary_sensor.housework_clean_bathroom', 'title') }}
            is due! Assigned to
            {{ state_attr('binary_sensor.housework_clean_bathroom', 'assignee_name') }}.
```

### Complete a task via NFC tag

```yaml
automation:
  - alias: "NFC complete bathroom cleaning"
    trigger:
      - platform: tag
        tag_id: my-bathroom-nfc-tag
    action:
      - service: housework.complete_task
        target:
          entity_id: binary_sensor.housework_clean_bathroom
        data:
          completed_by: person.alice
```

### Daily overdue summary

```yaml
automation:
  - alias: "Daily overdue chores notification"
    trigger:
      - platform: time
        at: "09:00:00"
    condition:
      - condition: numeric_state
        entity_id: sensor.housework_overdue_tasks
        above: 0
    action:
      - service: notify.mobile_app
        data:
          title: "Overdue chores"
          message: >
            {{ states('sensor.housework_overdue_tasks') }} overdue:
            {{ state_attr('sensor.housework_overdue_tasks', 'tasks') | join(', ') }}
```

## Options

Go to **Settings > Integrations > Housework > Configure** to set:

- **Default assignment strategy** — used when creating tasks without specifying one
- **Default priority** — used when creating tasks without specifying one

## Data storage

Task definitions are stored in HA's config entry subentries. Runtime state (due dates, completion history, assignee rotation, labels) is stored locally in `.storage/housework`. No external server or database required. Completion history is capped at 500 records.

## License

MIT
