"""Coordinator for Assigned Tasks."""

from __future__ import annotations

from collections.abc import Callable
import calendar
from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util

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
    MODE_ANY_ASSIGNEE,
    MODE_EACH_ASSIGNEE,
    UPDATE_ENTITY_ID,
    VALID_COMPLETION_MODES,
)
from .models import Person, Task, TaskList, new_id, parse_datetime, utc_iso
from .store import AssignedTasksStore

_LOGGER = logging.getLogger(__name__)

SIGNAL_UPDATED = f"{DOMAIN}_updated"
SIGNAL_PERSON_ADDED = f"{DOMAIN}_person_added"
SIGNAL_LIST_ADDED = f"{DOMAIN}_list_added"


class AssignedTasksCoordinator:
    """Owns assigned task state and lifecycle behavior."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize coordinator."""
        self.hass = hass
        self.entry = entry
        self.store = AssignedTasksStore(hass)
        self._unsub_interval: Callable[[], None] | None = None

    async def async_load(self) -> None:
        """Load persisted state and start timers."""
        await self.store.async_load()
        await self.async_sync_home_assistant_people()
        self._unsub_interval = async_track_time_interval(
            self.hass, self._async_tick, timedelta(minutes=1)
        )
        self._async_touch_update_entity()
        await self._async_tick(dt_util.utcnow())

    async def async_sync_home_assistant_people(self) -> None:
        """Mirror Home Assistant person entities into assignable people."""
        changed = False
        for state in self.hass.states.async_all("person"):
            name = (
                state.attributes.get("friendly_name")
                or state.name
                or state.entity_id.removeprefix("person.")
            )
            person = self.store.data.people.get(state.entity_id)
            if person is None:
                self.store.data.people[state.entity_id] = Person(
                    id=state.entity_id,
                    name=str(name),
                    enabled=True,
                )
                changed = True
            elif person.name != str(name):
                person.name = str(name)
                person.enabled = True
                changed = True
        if changed:
            await self.store.async_save()

    async def async_shutdown(self) -> None:
        """Stop background listeners."""
        if self._unsub_interval is not None:
            self._unsub_interval()
            self._unsub_interval = None

    @callback
    def async_person_entities(self) -> list[Person]:
        """Return enabled people that should have To-do entities."""
        return [
            person
            for person in sorted(
                self.store.data.people.values(), key=lambda item: item.name.lower()
            )
            if person.enabled
        ]

    @callback
    def async_task_list_entities(self) -> list[TaskList]:
        """Return task lists that should have To-do entities."""
        return sorted(
            (
                task_list
                for task_list in self.store.data.lists.values()
                if not task_list.archived
            ),
            key=lambda item: item.name.lower(),
        )

    def tasks_for_person(self, person_id: str) -> list[Task]:
        """Return visible tasks for a person."""
        now = dt_util.utcnow()
        tasks: list[Task] = []
        for task in self.store.data.tasks.values():
            if person_id not in task.assignees:
                continue
            task_list = self.store.data.lists.get(task.list_id)
            if task_list is None:
                continue
            if task_list.visible_to and person_id not in task_list.visible_to:
                continue
            if task.visible_to and person_id not in task.visible_to:
                continue
            if task_list.archived:
                continue
            if _is_expired(now, task.expires_at):
                continue
            tasks.append(task)
        return sorted(
            tasks,
            key=lambda task: (
                task.is_complete_for(person_id),
                task.due_at or task.expires_at or datetime.max.replace(tzinfo=dt_util.UTC),
                task.title.lower(),
            ),
        )

    async def async_add_person(
        self,
        name: str,
        *,
        person_id: str | None = None,
        notify_service: str | None = None,
        enabled: bool = True,
    ) -> Person:
        """Add a person."""
        person_id = _clean_id(person_id or name)
        if person_id in self.store.data.people:
            raise HomeAssistantError(f"Person already exists: {person_id}")
        person = Person(
            id=person_id,
            name=name,
            notify_service=notify_service,
            enabled=enabled,
        )
        self.store.data.people[person.id] = person
        await self._async_save_and_update()
        async_dispatcher_send(self.hass, SIGNAL_PERSON_ADDED, person.id)
        return person

    async def async_update_person(self, person_id: str, **changes: Any) -> None:
        """Update a person."""
        person = self._require_person(person_id)
        if ATTR_NAME in changes:
            person.name = changes[ATTR_NAME]
        if ATTR_NOTIFY_SERVICE in changes:
            person.notify_service = changes[ATTR_NOTIFY_SERVICE] or None
        if ATTR_ENABLED in changes:
            person.enabled = bool(changes[ATTR_ENABLED])
        await self._async_save_and_update()
        if person.enabled:
            async_dispatcher_send(self.hass, SIGNAL_PERSON_ADDED, person.id)

    async def async_remove_person(self, person_id: str) -> None:
        """Remove a person and their assignments."""
        self._require_person(person_id)
        self.store.data.people.pop(person_id)
        for task in self.store.data.tasks.values():
            if person_id in task.assignees:
                task.assignees.remove(person_id)
            if person_id in task.visible_to:
                task.visible_to.remove(person_id)
            task.completed_by.pop(person_id, None)
        for task_list in self.store.data.lists.values():
            if person_id in task_list.visible_to:
                task_list.visible_to.remove(person_id)
        await self._async_save_and_update()

    async def async_create_list(
        self,
        name: str,
        *,
        list_id: str | None = None,
        expires_at: datetime | None = None,
        resets_at: datetime | None = None,
        reset_interval: str | None = None,
        reset_every: int = 1,
        notify_before_minutes: int | None = None,
        visible_to: list[str] | None = None,
    ) -> TaskList:
        """Create a task list."""
        list_id = _clean_id(list_id or name)
        if list_id in self.store.data.lists:
            raise HomeAssistantError(f"List already exists: {list_id}")
        visible_to = [str(person_id) for person_id in (visible_to or [])]
        if visible_to:
            _validate_people(self.store.data.people, visible_to)
        task_list = TaskList(
            id=list_id,
            name=name,
            expires_at=expires_at,
            resets_at=resets_at,
            reset_interval=reset_interval,
            reset_every=max(1, int(reset_every or 1)),
            notify_before_minutes=notify_before_minutes,
            visible_to=list(dict.fromkeys(visible_to)),
        )
        self.store.data.lists[task_list.id] = task_list
        await self._async_save_and_update()
        async_dispatcher_send(self.hass, SIGNAL_LIST_ADDED, task_list.id)
        return task_list

    async def async_update_list(self, list_id: str, **changes: Any) -> None:
        """Update a task list."""
        task_list = self._require_list(list_id)
        _apply_schedule_changes(task_list, changes)
        if ATTR_NAME in changes:
            task_list.name = changes[ATTR_NAME]
        if ATTR_ARCHIVED in changes:
            task_list.archived = bool(changes[ATTR_ARCHIVED])
        if ATTR_VISIBLE_TO in changes:
            visible_to = [str(person_id) for person_id in changes[ATTR_VISIBLE_TO]]
            if visible_to:
                _validate_people(self.store.data.people, visible_to)
            task_list.visible_to = list(dict.fromkeys(visible_to))
        await self._async_save_and_update()
        if not task_list.archived:
            async_dispatcher_send(self.hass, SIGNAL_LIST_ADDED, task_list.id)

    async def async_archive_list(self, list_id: str) -> None:
        """Archive a task list without deleting its data."""
        task_list = self._require_list(list_id)
        task_list.archived = True
        await self._async_save_and_update()

    async def async_unarchive_list(self, list_id: str) -> None:
        """Unarchive a task list."""
        task_list = self._require_list(list_id)
        task_list.archived = False
        await self._async_save_and_update()
        async_dispatcher_send(self.hass, SIGNAL_LIST_ADDED, task_list.id)

    async def async_delete_list(self, list_id: str) -> None:
        """Delete a task list and all tasks in it."""
        self._require_list(list_id)
        self.store.data.lists.pop(list_id)
        for task_id in [
            task.id for task in self.store.data.tasks.values() if task.list_id == list_id
        ]:
            self.store.data.tasks.pop(task_id)
        await self._async_save_and_update()

    async def async_create_task(
        self,
        list_id: str,
        title: str,
        assignees: list[str],
        *,
        description: str | None = None,
        completion_mode: str = MODE_EACH_ASSIGNEE,
        due_at: datetime | None = None,
        expires_at: datetime | None = None,
        resets_at: datetime | None = None,
        reset_interval: str | None = None,
        reset_every: int = 1,
        notify_before_minutes: int | None = None,
        visible_to: list[str] | None = None,
    ) -> Task:
        """Create a task."""
        task_list = self._require_list(list_id)
        _validate_people(self.store.data.people, assignees)
        visible_to = [str(person_id) for person_id in (visible_to or [])]
        if visible_to:
            _validate_people(self.store.data.people, visible_to)
        if completion_mode not in VALID_COMPLETION_MODES:
            raise HomeAssistantError(f"Invalid completion mode: {completion_mode}")
        task = Task(
            id=new_id(),
            list_id=list_id,
            title=title,
            description=description,
            assignees=list(dict.fromkeys(assignees)),
            completion_mode=completion_mode,
            due_at=due_at,
            expires_at=expires_at,
            resets_at=resets_at,
            reset_interval=reset_interval,
            reset_every=max(1, int(reset_every or 1)),
            notify_before_minutes=notify_before_minutes,
            visible_to=list(dict.fromkeys(visible_to)),
        )
        self.store.data.tasks[task.id] = task
        await self._async_save_and_update()
        return task

    async def async_update_task(self, task_id: str, **changes: Any) -> None:
        """Update a task."""
        task = self._require_task(task_id)
        if ATTR_TITLE in changes:
            task.title = changes[ATTR_TITLE]
        if ATTR_DESCRIPTION in changes:
            task.description = changes[ATTR_DESCRIPTION] or None
        if ATTR_ASSIGNEES in changes:
            assignees = [str(person_id) for person_id in changes[ATTR_ASSIGNEES]]
            _validate_people(self.store.data.people, assignees)
            task.assignees = list(dict.fromkeys(assignees))
            task.completed_by = {
                person_id: completed_at
                for person_id, completed_at in task.completed_by.items()
                if person_id in task.assignees
            }
        if ATTR_COMPLETION_MODE in changes:
            completion_mode = changes[ATTR_COMPLETION_MODE]
            if completion_mode not in VALID_COMPLETION_MODES:
                raise HomeAssistantError(f"Invalid completion mode: {completion_mode}")
            task.completion_mode = completion_mode
        if ATTR_VISIBLE_TO in changes:
            visible_to = [str(person_id) for person_id in changes[ATTR_VISIBLE_TO]]
            if visible_to:
                _validate_people(self.store.data.people, visible_to)
            task.visible_to = list(dict.fromkeys(visible_to))
        _apply_schedule_changes(task, changes)
        if ATTR_DUE_AT in changes:
            task.due_at = changes[ATTR_DUE_AT]
        await self._async_save_and_update()

    async def async_delete_task(self, task_id: str) -> None:
        """Delete a task."""
        self._require_task(task_id)
        self.store.data.tasks.pop(task_id)
        await self._async_save_and_update()

    async def async_complete_assignment(
        self, task_id: str, person_id: str, complete: bool = True
    ) -> None:
        """Complete or reopen one person's assignment."""
        task = self._require_task(task_id)
        self._require_person(person_id)
        if person_id not in task.assignees:
            raise HomeAssistantError(f"{person_id} is not assigned to {task_id}")

        if complete:
            completed_at = utc_iso(dt_util.utcnow())
            if task.completion_mode == MODE_ANY_ASSIGNEE:
                task.completed_by = {
                    assigned_person_id: completed_at for assigned_person_id in task.assignees
                }
            else:
                task.completed_by[person_id] = completed_at
        else:
            if task.completion_mode == MODE_ANY_ASSIGNEE:
                task.completed_by.clear()
            else:
                task.completed_by.pop(person_id, None)
        await self._async_save_and_update()

    async def async_reset_list(self, list_id: str) -> None:
        """Clear all completions in a task list."""
        self._require_list(list_id)
        for task in self.store.data.tasks.values():
            if task.list_id == list_id:
                task.completed_by.clear()
                task.last_notified_at = None
        await self._async_save_and_update()

    async def _async_tick(self, now: datetime) -> None:
        """Handle reminders and resets."""
        now = dt_util.as_utc(now)
        changed = False
        for task_list in self.store.data.lists.values():
            if task_list.archived:
                continue

        for task in self.store.data.tasks.values():
            task_list = self.store.data.lists.get(task.list_id)
            if task_list is not None and task_list.archived:
                continue
            changed |= await self._async_maybe_notify_for_task(task, now)
            if task.resets_at and now >= task.resets_at:
                task.completed_by.clear()
                task.last_notified_at = None
                task.resets_at = _next_reset(
                    task.resets_at, task.reset_interval, task.reset_every
                )
                changed = True

        if changed:
            await self._async_save_and_update()

    async def _async_maybe_notify_for_task(self, task: Task, now: datetime) -> bool:
        """Notify remaining assignees when a task is near expiry or reset."""
        target = _next_boundary(task.expires_at, task.resets_at)
        lead_minutes = self._task_lead(task)
        if lead_minutes is None:
            return False
        if not _should_notify(now, target, task.last_notified_at, lead_minutes):
            return False
        people = [
            person_id
            for person_id in task.assignees
            if person_id not in task.completed_by
        ]
        if not people:
            return False
        await self._async_notify_people(
            people,
            f"{task.title} is coming due",
            f"This task needs attention before {dt_util.as_local(target).strftime('%Y-%m-%d %H:%M')}.",
        )
        task.last_notified_at = utc_iso(now)
        return True

    async def _async_notify_people(
        self, person_ids: list[str], title: str, message: str
    ) -> None:
        """Notify people by their configured notify service."""
        for person_id in sorted(set(person_ids)):
            person = self.store.data.people.get(person_id)
            if person is None or not person.enabled:
                continue
            if person.notify_service:
                domain, _, service = person.notify_service.partition(".")
                if domain and service:
                    await self.hass.services.async_call(
                        domain,
                        service,
                        {"title": title, "message": message},
                        blocking=False,
                    )
                    continue
                _LOGGER.warning(
                    "Invalid notify service for %s: %s",
                    person_id,
                    person.notify_service,
                )
            await self.hass.services.async_call(
                "persistent_notification",
                "create",
                {"title": title, "message": f"{person.name}: {message}"},
                blocking=False,
            )

    async def _async_save_and_update(self) -> None:
        """Persist state and notify entities and open frontend cards."""
        await self.store.async_save()
        async_dispatcher_send(self.hass, SIGNAL_UPDATED)
        self.hass.bus.async_fire(SIGNAL_UPDATED)
        self._async_touch_update_entity()

    @callback
    def _async_touch_update_entity(self) -> None:
        """Update a normal HA state so non-admin dashboards can refresh."""
        self.hass.states.async_set(
            UPDATE_ENTITY_ID,
            utc_iso(dt_util.utcnow()),
            {
                "friendly_name": "Assigned Tasks Updates",
                "icon": "mdi:clipboard-check-multiple",
            },
        )

    def _task_lead(self, task: Task) -> int | None:
        """Return task-specific notification lead time."""
        return task.notify_before_minutes

    def _require_person(self, person_id: str) -> Person:
        person = self.store.data.people.get(person_id)
        if person is None:
            raise HomeAssistantError(f"Unknown person: {person_id}")
        return person

    def _require_list(self, list_id: str) -> TaskList:
        task_list = self.store.data.lists.get(list_id)
        if task_list is None:
            raise HomeAssistantError(f"Unknown list: {list_id}")
        return task_list

    def _require_task(self, task_id: str) -> Task:
        task = self.store.data.tasks.get(task_id)
        if task is None:
            raise HomeAssistantError(f"Unknown task: {task_id}")
        return task


def _clean_id(value: str) -> str:
    """Create a stable id from user text."""
    cleaned = "".join(char.lower() if char.isalnum() else "_" for char in value.strip())
    cleaned = "_".join(part for part in cleaned.split("_") if part)
    if not cleaned:
        raise HomeAssistantError("ID cannot be empty")
    return cleaned


def _validate_people(people: dict[str, Person], assignees: list[str]) -> None:
    """Validate assignee ids."""
    if not assignees:
        raise HomeAssistantError("At least one assignee is required")
    unknown = sorted(set(assignees) - set(people))
    if unknown:
        raise HomeAssistantError(f"Unknown assignee(s): {', '.join(unknown)}")


def _apply_schedule_changes(target: Any, changes: dict[str, Any]) -> None:
    """Apply shared schedule fields."""
    if ATTR_EXPIRES_AT in changes:
        target.expires_at = changes[ATTR_EXPIRES_AT]
        target.last_notified_at = None
    if ATTR_RESETS_AT in changes:
        target.resets_at = changes[ATTR_RESETS_AT]
        target.last_notified_at = None
    if ATTR_RESET_INTERVAL in changes:
        target.reset_interval = changes[ATTR_RESET_INTERVAL] or None
    if ATTR_RESET_EVERY in changes:
        target.reset_every = max(1, int(changes[ATTR_RESET_EVERY] or 1))
    if ATTR_NOTIFY_BEFORE_MINUTES in changes:
        target.notify_before_minutes = changes[ATTR_NOTIFY_BEFORE_MINUTES]


def _is_expired(now: datetime, expires_at: datetime | None) -> bool:
    """Return if an expiry has passed."""
    return expires_at is not None and now >= expires_at


def _next_boundary(
    expires_at: datetime | None, resets_at: datetime | None
) -> datetime | None:
    """Return the next lifecycle boundary."""
    candidates = [value for value in (expires_at, resets_at) if value is not None]
    return min(candidates) if candidates else None


def _should_notify(
    now: datetime, target: datetime | None, last_notified_at: str | None, lead_minutes: int
) -> bool:
    """Return if a reminder should be sent."""
    if target is None or now >= target:
        return False
    if target - now > timedelta(minutes=lead_minutes):
        return False
    if last_notified_at:
        last = parse_datetime(last_notified_at)
        if last and last < target:
            return False
    return True


def _remaining_people(tasks: list[Task]) -> list[str]:
    """Return people with remaining work across tasks."""
    people: list[str] = []
    for task in tasks:
        if task.completion_mode == MODE_ANY_ASSIGNEE:
            if not task.completed_by:
                people.extend(task.assignees)
            continue
        people.extend(
            person_id
            for person_id in task.assignees
            if person_id not in task.completed_by
        )
    return people


def _next_reset(current: datetime, interval: str | None, every: int = 1) -> datetime | None:
    """Calculate the next reset time."""
    every = max(1, int(every or 1))
    if interval in (None, "", "none"):
        return None
    if interval == "daily":
        return current + timedelta(days=every)
    if interval == "weekly":
        return current + timedelta(weeks=every)
    if interval == "monthly":
        month = current.month + every
        year = current.year + (month - 1) // 12
        month = ((month - 1) % 12) + 1
        day = min(current.day, _last_day_of_month(year, month))
        return current.replace(year=year, month=month, day=day)
    if interval == "yearly":
        year = current.year + every
        month = current.month
        if month > 12:
            month = 1
            year += 1
        day = min(current.day, _last_day_of_month(year, month))
        return current.replace(year=year, month=month, day=day)
    raise HomeAssistantError(
        "reset_interval must be one of none, daily, weekly, monthly, or yearly"
    )


def _last_day_of_month(year: int, month: int) -> int:
    """Return the last day number for a month."""
    return calendar.monthrange(year, month)[1]
