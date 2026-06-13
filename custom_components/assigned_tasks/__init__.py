"""Assigned Tasks integration."""

from __future__ import annotations

import calendar
from datetime import timedelta
from pathlib import Path
from typing import Any

from aiohttp import web
from homeassistant.components import frontend
from homeassistant.components.http import HomeAssistantView, StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
import homeassistant.helpers.config_validation as cv
from homeassistant.util import dt as dt_util
import voluptuous as vol

from .const import (
    ATTR_ASSIGNEES,
    ATTR_ARCHIVED,
    ATTR_COMPLETION_MODE,
    ATTR_DESCRIPTION,
    ATTR_DUE_AT,
    ATTR_ENABLED,
    ATTR_EXPIRES_AT,
    ATTR_LIST_ID,
    ATTR_NAME,
    ATTR_NOTIFY_BEFORE_MINUTES,
    ATTR_NOTIFY_SERVICE,
    ATTR_PERSON_ID,
    ATTR_RESETS_AT,
    ATTR_RESET_EVERY,
    ATTR_RESET_INTERVAL,
    ATTR_TASK_ID,
    ATTR_TITLE,
    ATTR_VISIBLE_TO,
    DOMAIN,
    MODE_EACH_ASSIGNEE,
    MODE_ANY_ASSIGNEE,
    PLATFORMS,
    SERVICE_ADD_PERSON,
    SERVICE_ARCHIVE_LIST,
    SERVICE_COMPLETE_ASSIGNMENT,
    SERVICE_CREATE_LIST,
    SERVICE_CREATE_TASK,
    SERVICE_DELETE_LIST,
    SERVICE_DELETE_TASK,
    SERVICE_REMOVE_PERSON,
    SERVICE_RESET_LIST,
    SERVICE_UPDATE_LIST,
    SERVICE_UPDATE_PERSON,
    SERVICE_UPDATE_TASK,
    SERVICE_UNARCHIVE_LIST,
    VALID_COMPLETION_MODES,
)
from .coordinator import AssignedTasksCoordinator
from .models import parse_datetime, utc_iso

AssignedTasksConfigEntry = ConfigEntry
FRONTEND_VERSION = "20260613.0006"
FRONTEND_MODULE = f"assigned-tasks-card-{FRONTEND_VERSION}.js"


async def async_setup_entry(hass: HomeAssistant, entry: AssignedTasksConfigEntry) -> bool:
    """Set up Assigned Tasks from a config entry."""
    coordinator = AssignedTasksCoordinator(hass, entry)
    entry.runtime_data = coordinator

    await coordinator.async_load()
    if PLATFORMS:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await _async_register_services(hass)
    await _async_register_frontend(hass)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: AssignedTasksConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = True
    if PLATFORMS:
        unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        await entry.runtime_data.async_shutdown()
    return unload_ok


async def _async_register_frontend(hass: HomeAssistant) -> None:
    """Register the Assigned Tasks frontend and API views."""
    static_path = Path(__file__).parent / "frontend"
    await hass.http.async_register_static_paths(
        [
            StaticPathConfig(
                "/assigned_tasks_static",
                str(static_path),
                cache_headers=False,
            )
        ]
    )
    if frontend.async_panel_exists(hass, "assigned-tasks"):
        frontend.async_remove_panel(hass, "assigned-tasks")
    frontend.async_register_built_in_panel(
        hass,
        component_name="custom",
        sidebar_title="Assigned Tasks",
        sidebar_icon="mdi:clipboard-check-multiple",
        frontend_url_path="assigned-tasks",
        config={
            "_panel_custom": {
                "name": "assigned-tasks-panel",
                "module_url": f"/assigned_tasks_static/{FRONTEND_MODULE}",
                "embed_iframe": False,
                "trust_external": False,
            }
        },
        require_admin=False,
        update=True,
    )

    if hass.data.setdefault(DOMAIN, {}).get("api_registered"):
        return
    hass.http.register_view(AssignedTasksStateView)
    hass.http.register_view(AssignedTasksPeopleView)
    hass.http.register_view(AssignedTasksListsView)
    hass.http.register_view(AssignedTasksListView)
    hass.http.register_view(AssignedTasksTasksView)
    hass.http.register_view(AssignedTasksTaskView)
    hass.http.register_view(AssignedTasksAssignmentView)
    hass.data[DOMAIN]["api_registered"] = True


async def _async_register_services(hass: HomeAssistant) -> None:
    """Register integration services."""
    if hass.services.has_service(DOMAIN, SERVICE_ADD_PERSON):
        return

    def coordinator() -> AssignedTasksCoordinator:
        entries = hass.config_entries.async_entries(DOMAIN)
        if not entries:
            raise HomeAssistantError("Assigned Tasks is not configured")
        return entries[0].runtime_data

    async def add_person(call: ServiceCall) -> None:
        await coordinator().async_add_person(
            call.data[ATTR_NAME],
            person_id=call.data.get(ATTR_PERSON_ID),
            notify_service=call.data.get(ATTR_NOTIFY_SERVICE),
            enabled=call.data.get(ATTR_ENABLED, True),
        )

    async def update_person(call: ServiceCall) -> None:
        await coordinator().async_update_person(
            call.data[ATTR_PERSON_ID], **_optional(call.data, PERSON_UPDATE_FIELDS)
        )

    async def remove_person(call: ServiceCall) -> None:
        await coordinator().async_remove_person(call.data[ATTR_PERSON_ID])

    async def create_list(call: ServiceCall) -> None:
        await coordinator().async_create_list(
            call.data[ATTR_NAME],
            list_id=call.data.get(ATTR_LIST_ID),
            expires_at=_parse(call.data.get(ATTR_EXPIRES_AT)),
            resets_at=_parse(call.data.get(ATTR_RESETS_AT)),
            reset_interval=call.data.get(ATTR_RESET_INTERVAL),
            reset_every=call.data.get(ATTR_RESET_EVERY, 1),
            notify_before_minutes=call.data.get(ATTR_NOTIFY_BEFORE_MINUTES),
            visible_to=[str(item) for item in call.data.get(ATTR_VISIBLE_TO, [])],
        )

    async def update_list(call: ServiceCall) -> None:
        await coordinator().async_update_list(
            call.data[ATTR_LIST_ID], **_schedule_changes(call.data)
        )

    async def archive_list(call: ServiceCall) -> None:
        await coordinator().async_archive_list(call.data[ATTR_LIST_ID])

    async def unarchive_list(call: ServiceCall) -> None:
        await coordinator().async_unarchive_list(call.data[ATTR_LIST_ID])

    async def delete_list(call: ServiceCall) -> None:
        await coordinator().async_delete_list(call.data[ATTR_LIST_ID])

    async def create_task(call: ServiceCall) -> None:
        await coordinator().async_create_task(
            call.data[ATTR_LIST_ID],
            call.data[ATTR_TITLE],
            [str(item) for item in call.data[ATTR_ASSIGNEES]],
            description=call.data.get(ATTR_DESCRIPTION),
            completion_mode=call.data.get(ATTR_COMPLETION_MODE, MODE_EACH_ASSIGNEE),
            due_at=_parse(call.data.get(ATTR_DUE_AT)),
            expires_at=_parse(call.data.get(ATTR_EXPIRES_AT)),
            resets_at=_parse(call.data.get(ATTR_RESETS_AT)),
            reset_interval=call.data.get(ATTR_RESET_INTERVAL),
            reset_every=call.data.get(ATTR_RESET_EVERY, 1),
            notify_before_minutes=call.data.get(ATTR_NOTIFY_BEFORE_MINUTES),
            visible_to=[str(item) for item in call.data.get(ATTR_VISIBLE_TO, [])],
        )

    async def update_task(call: ServiceCall) -> None:
        changes = _optional(call.data, TASK_UPDATE_FIELDS)
        changes.update(_schedule_changes(call.data))
        if ATTR_DUE_AT in call.data:
            changes[ATTR_DUE_AT] = _parse(call.data.get(ATTR_DUE_AT))
        await coordinator().async_update_task(call.data[ATTR_TASK_ID], **changes)

    async def delete_task(call: ServiceCall) -> None:
        await coordinator().async_delete_task(call.data[ATTR_TASK_ID])

    async def complete_assignment(call: ServiceCall) -> None:
        await coordinator().async_complete_assignment(
            call.data[ATTR_TASK_ID],
            call.data[ATTR_PERSON_ID],
            call.data.get("complete", True),
        )

    async def reset_list(call: ServiceCall) -> None:
        await coordinator().async_reset_list(call.data[ATTR_LIST_ID])

    hass.services.async_register(
        DOMAIN,
        SERVICE_ADD_PERSON,
        add_person,
        schema=vol.Schema(
            {
                vol.Required(ATTR_NAME): cv.string,
                vol.Optional(ATTR_PERSON_ID): cv.string,
                vol.Optional(ATTR_NOTIFY_SERVICE): cv.string,
                vol.Optional(ATTR_ENABLED, default=True): cv.boolean,
            }
        ),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_UPDATE_PERSON,
        update_person,
        schema=vol.Schema(
            {
                vol.Required(ATTR_PERSON_ID): cv.string,
                vol.Optional(ATTR_NAME): cv.string,
                vol.Optional(ATTR_NOTIFY_SERVICE): cv.string,
                vol.Optional(ATTR_ENABLED): cv.boolean,
            }
        ),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_REMOVE_PERSON,
        remove_person,
        schema=vol.Schema({vol.Required(ATTR_PERSON_ID): cv.string}),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_CREATE_LIST,
        create_list,
        schema=_list_schema(require_name=True),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_UPDATE_LIST,
        update_list,
        schema=_list_schema(require_name=False),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_ARCHIVE_LIST,
        archive_list,
        schema=vol.Schema({vol.Required(ATTR_LIST_ID): cv.string}),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_UNARCHIVE_LIST,
        unarchive_list,
        schema=vol.Schema({vol.Required(ATTR_LIST_ID): cv.string}),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_DELETE_LIST,
        delete_list,
        schema=vol.Schema({vol.Required(ATTR_LIST_ID): cv.string}),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_CREATE_TASK,
        create_task,
        schema=vol.Schema(
            {
                vol.Required(ATTR_LIST_ID): cv.string,
                vol.Required(ATTR_TITLE): cv.string,
                vol.Required(ATTR_ASSIGNEES): cv.ensure_list,
                vol.Optional(ATTR_DESCRIPTION): cv.string,
                vol.Optional(ATTR_VISIBLE_TO, default=[]): cv.ensure_list,
                vol.Optional(ATTR_COMPLETION_MODE, default=MODE_EACH_ASSIGNEE): vol.In(
                    sorted(VALID_COMPLETION_MODES)
                ),
                vol.Optional(ATTR_DUE_AT): cv.string,
                vol.Optional(ATTR_EXPIRES_AT): cv.string,
                vol.Optional(ATTR_RESETS_AT): cv.string,
                vol.Optional(ATTR_RESET_INTERVAL): vol.In(
                    ["none", "daily", "weekly", "monthly", "yearly"]
                ),
                vol.Optional(ATTR_RESET_EVERY, default=1): vol.All(
                    vol.Coerce(int), vol.Range(min=1, max=365)
                ),
                vol.Optional(ATTR_NOTIFY_BEFORE_MINUTES): vol.All(
                    vol.Coerce(int), vol.Range(min=1, max=10080)
                ),
            }
        ),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_UPDATE_TASK,
        update_task,
        schema=vol.Schema(
            {
                vol.Required(ATTR_TASK_ID): cv.string,
                vol.Optional(ATTR_TITLE): cv.string,
                vol.Optional(ATTR_DESCRIPTION): cv.string,
                vol.Optional(ATTR_ASSIGNEES): cv.ensure_list,
                vol.Optional(ATTR_VISIBLE_TO): cv.ensure_list,
                vol.Optional(ATTR_COMPLETION_MODE): vol.In(
                    sorted(VALID_COMPLETION_MODES)
                ),
                vol.Optional(ATTR_DUE_AT): cv.string,
                vol.Optional(ATTR_EXPIRES_AT): cv.string,
                vol.Optional(ATTR_RESETS_AT): cv.string,
                vol.Optional(ATTR_RESET_INTERVAL): vol.In(
                    ["none", "daily", "weekly", "monthly", "yearly"]
                ),
                vol.Optional(ATTR_RESET_EVERY): vol.All(
                    vol.Coerce(int), vol.Range(min=1, max=365)
                ),
                vol.Optional(ATTR_NOTIFY_BEFORE_MINUTES): vol.All(
                    vol.Coerce(int), vol.Range(min=1, max=10080)
                ),
            }
        ),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_DELETE_TASK,
        delete_task,
        schema=vol.Schema({vol.Required(ATTR_TASK_ID): cv.string}),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_COMPLETE_ASSIGNMENT,
        complete_assignment,
        schema=vol.Schema(
            {
                vol.Required(ATTR_TASK_ID): cv.string,
                vol.Required(ATTR_PERSON_ID): cv.string,
                vol.Optional("complete", default=True): cv.boolean,
            }
        ),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_RESET_LIST,
        reset_list,
        schema=vol.Schema({vol.Required(ATTR_LIST_ID): cv.string}),
    )


PERSON_UPDATE_FIELDS = {ATTR_NAME, ATTR_NOTIFY_SERVICE, ATTR_ENABLED}
TASK_UPDATE_FIELDS = {ATTR_TITLE, ATTR_DESCRIPTION, ATTR_ASSIGNEES, ATTR_COMPLETION_MODE}


def _optional(data: dict[str, Any], keys: set[str]) -> dict[str, Any]:
    """Return keys that were supplied by a service call."""
    return {key: data[key] for key in keys if key in data}


def _parse(value: Any) -> Any:
    """Parse optional datetime service input."""
    if isinstance(value, str) and len(value) == 10 and value[4] == "-" and value[7] == "-":
        value = f"{value}T23:59:59"
    return parse_datetime(value)


def _schedule_changes(data: dict[str, Any]) -> dict[str, Any]:
    """Return schedule fields from service data."""
    changes: dict[str, Any] = {}
    if ATTR_NAME in data:
        changes[ATTR_NAME] = data[ATTR_NAME]
    if ATTR_EXPIRES_AT in data:
        changes[ATTR_EXPIRES_AT] = _parse(data.get(ATTR_EXPIRES_AT))
    if ATTR_RESETS_AT in data:
        changes[ATTR_RESETS_AT] = _parse(data.get(ATTR_RESETS_AT))
    if ATTR_RESET_INTERVAL in data:
        changes[ATTR_RESET_INTERVAL] = data.get(ATTR_RESET_INTERVAL)
    if ATTR_RESET_EVERY in data:
        changes[ATTR_RESET_EVERY] = data.get(ATTR_RESET_EVERY)
    if ATTR_NOTIFY_BEFORE_MINUTES in data:
        changes[ATTR_NOTIFY_BEFORE_MINUTES] = data.get(ATTR_NOTIFY_BEFORE_MINUTES)
    if ATTR_ARCHIVED in data:
        changes[ATTR_ARCHIVED] = data.get(ATTR_ARCHIVED)
    if ATTR_VISIBLE_TO in data:
        changes[ATTR_VISIBLE_TO] = data.get(ATTR_VISIBLE_TO)
    return changes


def _list_schema(*, require_name: bool) -> vol.Schema:
    """Return service schema for creating/updating lists."""
    fields: dict[Any, Any] = {
        vol.Required(ATTR_LIST_ID) if not require_name else vol.Optional(ATTR_LIST_ID): cv.string,
        vol.Required(ATTR_NAME) if require_name else vol.Optional(ATTR_NAME): cv.string,
        vol.Optional(ATTR_EXPIRES_AT): cv.string,
        vol.Optional(ATTR_RESETS_AT): cv.string,
        vol.Optional(ATTR_RESET_INTERVAL): vol.In(
            ["none", "daily", "weekly", "monthly", "yearly"]
        ),
        vol.Optional(ATTR_RESET_EVERY): vol.All(vol.Coerce(int), vol.Range(min=1, max=365)),
        vol.Optional(ATTR_NOTIFY_BEFORE_MINUTES): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=10080)
        ),
        vol.Optional(ATTR_VISIBLE_TO): cv.ensure_list,
        vol.Optional(ATTR_ARCHIVED): cv.boolean,
    }
    return vol.Schema(fields)


def _coordinator_from_hass(hass: HomeAssistant) -> AssignedTasksCoordinator:
    """Return the configured coordinator."""
    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        raise HomeAssistantError("Assigned Tasks is not configured")
    return entries[0].runtime_data


def _state_payload(
    coordinator: AssignedTasksCoordinator, *, can_toggle_assignments: bool = False
) -> dict[str, Any]:
    """Return API state payload."""
    people = []
    for person in sorted(
        coordinator.store.data.people.values(), key=lambda item: item.name.lower()
    ):
        data = person.as_dict()
        state = coordinator.hass.states.get(person.id)
        if state is not None:
            data["user_id"] = state.attributes.get("user_id")
            data["entity_id"] = state.entity_id
        people.append(data)
    lists = []
    for task_list in sorted(
        coordinator.store.data.lists.values(), key=lambda item: item.name.lower()
    ):
        data = task_list.as_dict()
        data["computed_due_at"] = None
        lists.append(data)
    tasks = []
    for task in sorted(
        coordinator.store.data.tasks.values(), key=lambda item: item.title.lower()
    ):
        task_list = coordinator.store.data.lists.get(task.list_id)
        data = task.as_dict()
        data["computed_due_at"] = utc_iso(
            _next_due_at(
                task.expires_at,
                task.resets_at,
                task.reset_interval,
                task.reset_every,
            )
        )
        data["assignee_names"] = [
            coordinator.store.data.people[person_id].name
            for person_id in task.assignees
            if person_id in coordinator.store.data.people
        ]
        data["completion_label"] = (
            "Any one assigned person completes it for everyone"
            if task.completion_mode == MODE_ANY_ASSIGNEE
            else "Every assigned person must complete it"
        )
        tasks.append(data)
    return {
        "people": people,
        "lists": lists,
        "tasks": tasks,
        "permissions": {"can_toggle_assignments": can_toggle_assignments},
    }


def _can_toggle_assignments(request) -> bool:
    """Return if the current request user can toggle any assignment."""
    return bool(getattr(request.get("hass_user"), "is_admin", False))


def _person_id_for_request_user(
    coordinator: AssignedTasksCoordinator, request
) -> str | None:
    """Return the HA person entity id linked to the request user."""
    user_id = getattr(request.get("hass_user"), "id", None)
    if user_id is None:
        return None
    for state in coordinator.hass.states.async_all("person"):
        if state.attributes.get("user_id") == user_id:
            return state.entity_id
    return None


def _ensure_can_toggle_assignment(
    coordinator: AssignedTasksCoordinator, request, person_id: str
) -> None:
    """Block non-admin users from toggling another person's assignment."""
    if _can_toggle_assignments(request):
        return
    if person_id == _person_id_for_request_user(coordinator, request):
        return
    raise web.HTTPForbidden(text="Only admins can update another person's assignment")


def _next_due_at(expires_at, resets_at, reset_interval=None, reset_every=1):
    """Return the next visible due boundary for a scheduled item."""
    now = dt_util.utcnow()
    if resets_at is not None and reset_interval in ("daily", "weekly", "monthly", "yearly"):
        every = max(1, int(reset_every or 1))
        due_at = resets_at
        while due_at.date() <= now.date():
            due_at = _next_recurring_due_at(due_at, reset_interval, every)
        return due_at
    candidates = [
        value
        for value in (expires_at, resets_at)
        if value is not None and value >= now
    ]
    return min(candidates) if candidates else None


def _next_recurring_due_at(current, interval, every):
    """Calculate the next displayed due boundary for a repeating task."""
    if interval == "daily":
        return current + timedelta(days=every)
    if interval == "weekly":
        return current + timedelta(weeks=every)
    if interval == "monthly":
        month = current.month + every
        year = current.year + (month - 1) // 12
        month = ((month - 1) % 12) + 1
        day = min(current.day, calendar.monthrange(year, month)[1])
        return current.replace(year=year, month=month, day=day)
    if interval == "yearly":
        year = current.year + every
        day = min(current.day, calendar.monthrange(year, current.month)[1])
        return current.replace(year=year, day=day)
    return current


class AssignedTasksStateView(HomeAssistantView):
    """Return Assigned Tasks state."""

    url = "/api/assigned_tasks/state"
    name = "api:assigned_tasks:state"

    async def get(self, request):
        """Handle state request."""
        coordinator = _coordinator_from_hass(request.app["hass"])
        await coordinator.async_sync_home_assistant_people()
        return self.json(
            _state_payload(
                coordinator,
                can_toggle_assignments=_can_toggle_assignments(request),
            )
        )


class AssignedTasksPeopleView(HomeAssistantView):
    """Create people."""

    url = "/api/assigned_tasks/people"
    name = "api:assigned_tasks:people"

    async def post(self, request):
        """Create a person."""
        coordinator = _coordinator_from_hass(request.app["hass"])
        data = await request.json()
        await coordinator.async_add_person(
            data["name"],
            person_id=data.get("person_id"),
            notify_service=data.get("notify_service"),
            enabled=data.get("enabled", True),
        )
        return self.json(
            _state_payload(
                coordinator,
                can_toggle_assignments=_can_toggle_assignments(request),
            )
        )


class AssignedTasksListsView(HomeAssistantView):
    """Create lists."""

    url = "/api/assigned_tasks/lists"
    name = "api:assigned_tasks:lists"

    async def post(self, request):
        """Create a task list."""
        coordinator = _coordinator_from_hass(request.app["hass"])
        data = await request.json()
        await coordinator.async_create_list(
            data["name"],
            list_id=data.get("list_id"),
            expires_at=_parse(data.get("expires_at")),
            resets_at=_parse(data.get("resets_at")),
            reset_interval=data.get("reset_interval"),
            reset_every=data.get("reset_every", 1),
            notify_before_minutes=data.get("notify_before_minutes"),
            visible_to=[str(person_id) for person_id in data.get(ATTR_VISIBLE_TO, [])],
        )
        return self.json(
            _state_payload(
                coordinator,
                can_toggle_assignments=_can_toggle_assignments(request),
            )
        )


class AssignedTasksListView(HomeAssistantView):
    """Update a list."""

    url = "/api/assigned_tasks/lists/{list_id}"
    name = "api:assigned_tasks:list"

    async def patch(self, request, list_id):
        """Update a task list."""
        coordinator = _coordinator_from_hass(request.app["hass"])
        data = await request.json()
        action = data.get("action")
        if action == "archive":
            await coordinator.async_archive_list(list_id)
        elif action == "unarchive":
            await coordinator.async_unarchive_list(list_id)
        else:
            changes = {}
            for key in (
                ATTR_NAME,
                ATTR_EXPIRES_AT,
                ATTR_RESETS_AT,
                ATTR_RESET_INTERVAL,
                ATTR_RESET_EVERY,
                ATTR_NOTIFY_BEFORE_MINUTES,
                ATTR_ARCHIVED,
                ATTR_VISIBLE_TO,
            ):
                if key in data:
                    changes[key] = data[key]
            if ATTR_EXPIRES_AT in changes:
                changes[ATTR_EXPIRES_AT] = _parse(changes[ATTR_EXPIRES_AT])
            if ATTR_RESETS_AT in changes:
                changes[ATTR_RESETS_AT] = _parse(changes[ATTR_RESETS_AT])
            await coordinator.async_update_list(list_id, **changes)
        return self.json(
            _state_payload(
                coordinator,
                can_toggle_assignments=_can_toggle_assignments(request),
            )
        )


class AssignedTasksTasksView(HomeAssistantView):
    """Create tasks."""

    url = "/api/assigned_tasks/tasks"
    name = "api:assigned_tasks:tasks"

    async def post(self, request):
        """Create a task."""
        coordinator = _coordinator_from_hass(request.app["hass"])
        await coordinator.async_sync_home_assistant_people()
        data = await request.json()
        await coordinator.async_create_task(
            data[ATTR_LIST_ID],
            data[ATTR_TITLE],
            [str(person_id) for person_id in data.get(ATTR_ASSIGNEES, [])],
            description=data.get(ATTR_DESCRIPTION),
            completion_mode=data.get(ATTR_COMPLETION_MODE, MODE_EACH_ASSIGNEE),
            expires_at=_parse(data.get(ATTR_EXPIRES_AT)),
            resets_at=_parse(data.get(ATTR_RESETS_AT)),
            reset_interval=data.get(ATTR_RESET_INTERVAL),
            reset_every=data.get(ATTR_RESET_EVERY, 1),
            notify_before_minutes=data.get(ATTR_NOTIFY_BEFORE_MINUTES),
            visible_to=[str(person_id) for person_id in data.get(ATTR_VISIBLE_TO, [])],
        )
        return self.json(
            _state_payload(
                coordinator,
                can_toggle_assignments=_can_toggle_assignments(request),
            )
        )


class AssignedTasksTaskView(HomeAssistantView):
    """Update or delete a task."""

    url = "/api/assigned_tasks/tasks/{task_id}"
    name = "api:assigned_tasks:task"

    async def patch(self, request, task_id):
        """Update a task."""
        coordinator = _coordinator_from_hass(request.app["hass"])
        data = await request.json()
        changes = {}
        for key in (
            ATTR_TITLE,
            ATTR_DESCRIPTION,
            ATTR_ASSIGNEES,
            ATTR_COMPLETION_MODE,
            ATTR_EXPIRES_AT,
            ATTR_RESETS_AT,
            ATTR_RESET_INTERVAL,
            ATTR_RESET_EVERY,
            ATTR_NOTIFY_BEFORE_MINUTES,
            ATTR_VISIBLE_TO,
        ):
            if key in data:
                changes[key] = data[key]
        for key in (ATTR_EXPIRES_AT, ATTR_RESETS_AT):
            if key in changes:
                changes[key] = _parse(changes[key])
        await coordinator.async_update_task(task_id, **changes)
        return self.json(
            _state_payload(
                coordinator,
                can_toggle_assignments=_can_toggle_assignments(request),
            )
        )

    async def delete(self, request, task_id):
        """Delete a task."""
        coordinator = _coordinator_from_hass(request.app["hass"])
        await coordinator.async_delete_task(task_id)
        return self.json(
            _state_payload(
                coordinator,
                can_toggle_assignments=_can_toggle_assignments(request),
            )
        )


class AssignedTasksAssignmentView(HomeAssistantView):
    """Complete or reopen one person's assignment."""

    url = "/api/assigned_tasks/tasks/{task_id}/assignments/{person_id}"
    name = "api:assigned_tasks:assignment"

    async def patch(self, request, task_id, person_id):
        """Update assignment completion."""
        coordinator = _coordinator_from_hass(request.app["hass"])
        await coordinator.async_sync_home_assistant_people()
        _ensure_can_toggle_assignment(coordinator, request, person_id)
        data = await request.json()
        await coordinator.async_complete_assignment(
            task_id,
            person_id,
            data.get("complete", True),
        )
        return self.json(
            _state_payload(
                coordinator,
                can_toggle_assignments=_can_toggle_assignments(request),
            )
        )
