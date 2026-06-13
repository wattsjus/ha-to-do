"""Constants for Assigned Tasks."""

from __future__ import annotations

DOMAIN = "assigned_tasks"
UPDATE_ENTITY_ID = "sensor.assigned_tasks_updates"
STORAGE_KEY = f"{DOMAIN}.storage"
STORAGE_VERSION = 1

PLATFORMS = []

MODE_EACH_ASSIGNEE = "each_assignee"
MODE_ANY_ASSIGNEE = "any_assignee"
VALID_COMPLETION_MODES = {MODE_EACH_ASSIGNEE, MODE_ANY_ASSIGNEE}

SERVICE_ADD_PERSON = "add_person"
SERVICE_UPDATE_PERSON = "update_person"
SERVICE_REMOVE_PERSON = "remove_person"
SERVICE_CREATE_LIST = "create_list"
SERVICE_UPDATE_LIST = "update_list"
SERVICE_ARCHIVE_LIST = "archive_list"
SERVICE_UNARCHIVE_LIST = "unarchive_list"
SERVICE_DELETE_LIST = "delete_list"
SERVICE_CREATE_TASK = "create_task"
SERVICE_UPDATE_TASK = "update_task"
SERVICE_DELETE_TASK = "delete_task"
SERVICE_COMPLETE_ASSIGNMENT = "complete_assignment"
SERVICE_RESET_LIST = "reset_list"

ATTR_PERSON_ID = "person_id"
ATTR_NAME = "name"
ATTR_NOTIFY_SERVICE = "notify_service"
ATTR_ENABLED = "enabled"
ATTR_ARCHIVED = "archived"
ATTR_LIST_ID = "list_id"
ATTR_TASK_ID = "task_id"
ATTR_TITLE = "title"
ATTR_DESCRIPTION = "description"
ATTR_ASSIGNEES = "assignees"
ATTR_COMPLETION_MODE = "completion_mode"
ATTR_VISIBLE_TO = "visible_to"
ATTR_EXPIRES_AT = "expires_at"
ATTR_RESETS_AT = "resets_at"
ATTR_RESET_INTERVAL = "reset_interval"
ATTR_RESET_EVERY = "reset_every"
ATTR_WEEKLY_DAYS = "weekly_days"
ATTR_NOTIFY_BEFORE_MINUTES = "notify_before_minutes"
ATTR_DUE_AT = "due_at"
ATTR_PERSON = "person"
