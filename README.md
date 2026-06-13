# Assigned Tasks for Home Assistant

[![Open your Home Assistant instance and add this repository to HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=wattsjus&repository=ha-to-do&category=integration)

Assigned Tasks is a Home Assistant custom integration for assigning shared tasks to people. Each person gets a filtered To-do entity so standard Home Assistant To-do cards can show only that person's work.

## What it does

- Assign one task to one or more people.
- Choose whether each assignee must complete their own assignment or whether any assignee completes the whole task.
- Defaults to `each_assignee`.
- Add expiration and reset settings to lists and individual tasks.

## Install

Use the button above to add this repository to HACS as a custom integration repository.

For manual installation, copy `custom_components/assigned_tasks` into your Home Assistant config directory:

```bash
scp -r custom_components/assigned_tasks user@home-assistant-host:/usr/share/hassio/homeassistant/custom_components/
```

Restart Home Assistant, then add **Assigned Tasks** from **Settings > Devices & services > Add integration**.

## Basic setup

Assigned Tasks adds its own **Assigned Tasks** sidebar item. Use that panel for the main workflow: add people, create/archive lists, create/edit/delete tasks, assign multiple people, and choose completion behavior.

The Lovelace card remains available if you want dashboard widgets:

```yaml
type: custom:assigned-tasks-card
title: Assigned Tasks
```

For a person-filtered card:

```yaml
type: custom:assigned-tasks-card
title: Justin's Tasks
person_id: justin
```

For the currently logged-in Home Assistant user:

```yaml
type: custom:assigned-tasks-card
title: My Tasks
current_user: true
```

The filtered cards show only tasks assigned to that person and let them mark their assignment done or reopen it.

For a simple viewer card:

```yaml
type: custom:assigned-tasks-card
title: My Tasks
view: simple
current_user: true
```

The card includes a visual editor in Lovelace. Use it to choose the people and task lists shown by the card.

By default, the card shows all non-archived task lists that apply to the configured person or current user. To show only one task list, set `list_id`:

```yaml
type: custom:assigned-tasks-card
title: Chores
view: simple
current_user: true
list_id: chores
```

To show multiple people or multiple lists, use `person_ids` and `list_ids`:

```yaml
type: custom:assigned-tasks-card
title: Kids' Tasks
view: simple
person_ids:
  - joshua
  - alex
list_ids:
  - chores
  - school
```

The card lets you add people, create/archive lists, create/edit/delete tasks, choose multiple assignees, and choose whether every assigned person must complete the task or whether any one assigned person completes it for everyone.

Use Home Assistant actions/services for assignment metadata that the built-in To-do list dialog cannot represent, such as assigned people, completion behavior, archiving, and unarchiving.

The services below are useful for automations or bulk setup.

Add people first. The `person_id` is the id used in task assignments.

```yaml
service: assigned_tasks.add_person
data:
  person_id: justin
  name: Justin
```

```yaml
service: assigned_tasks.add_person
data:
  person_id: alex
  name: Alex
```

Create a list:

```yaml
service: assigned_tasks.create_list
data:
  list_id: chores
  name: Chores
  resets_at: "2026-05-31T08:00:00-05:00"
  reset_interval: daily
```

Create a task where everyone completes their own assignment:

```yaml
service: assigned_tasks.create_task
data:
  list_id: chores
  title: Take out trash
  assignees:
    - justin
    - alex
```

Create a task where one person can complete it for everyone:

```yaml
service: assigned_tasks.create_task
data:
  list_id: chores
  title: Bring bins back from curb
  assignees:
    - justin
    - alex
  completion_mode: any_assignee
```

## Dashboard cards

After adding people, Home Assistant will create To-do entities such as:

- `todo.justin_tasks`
- `todo.alex_tasks`

Use the built-in To-do List card:

```yaml
type: todo-list
entity: todo.justin_tasks
title: Justin's Tasks
```

```yaml
type: todo-list
entity: todo.alex_tasks
title: Alex's Tasks
```

When a person checks off an item, the component records completion for that person. If the task uses `any_assignee`, checking it off completes it for every assignee.

## Reset and expiration

Lists and tasks support:

- `expires_at`: hides the task/list after the time passes.
- `resets_at`: clears completions when the time passes.
- `reset_interval`: `none`, `daily`, `weekly`, or `monthly`.
