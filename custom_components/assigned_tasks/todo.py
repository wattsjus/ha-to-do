"""To-do entities for Assigned Tasks."""

from __future__ import annotations

from datetime import date, datetime, time

from homeassistant.components.todo import TodoItem, TodoItemStatus, TodoListEntity
try:
    from homeassistant.components.todo import TodoListEntityFeature
except ImportError:  # pragma: no cover - older Home Assistant fallback
    TodoListEntityFeature = None
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import DOMAIN, MODE_ANY_ASSIGNEE, MODE_EACH_ASSIGNEE
from .coordinator import (
    AssignedTasksCoordinator,
    SIGNAL_LIST_ADDED,
    SIGNAL_PERSON_ADDED,
    SIGNAL_UPDATED,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Assigned Tasks to-do entities."""
    coordinator: AssignedTasksCoordinator = entry.runtime_data
    added_people: set[str] = set()
    added_lists: set[str] = set()

    @callback
    def add_person_entity(person_id: str) -> None:
        if person_id in added_people:
            return
        person = coordinator.store.data.people.get(person_id)
        if person is None or not person.enabled:
            return
        added_people.add(person_id)
        async_add_entities([AssignedPersonTodoEntity(coordinator, person_id)])

    @callback
    def add_task_list_entity(list_id: str) -> None:
        if list_id in added_lists:
            return
        task_list = coordinator.store.data.lists.get(list_id)
        if task_list is None or task_list.archived:
            return
        added_lists.add(list_id)
        async_add_entities([AssignedTaskListTodoEntity(coordinator, list_id)])

    for person in coordinator.async_person_entities():
        add_person_entity(person.id)
    for task_list in coordinator.async_task_list_entities():
        add_task_list_entity(task_list.id)

    entry.async_on_unload(
        async_dispatcher_connect(hass, SIGNAL_PERSON_ADDED, add_person_entity)
    )
    entry.async_on_unload(
        async_dispatcher_connect(hass, SIGNAL_LIST_ADDED, add_task_list_entity)
    )


class AssignedPersonTodoEntity(TodoListEntity):
    """A per-person assigned task To-do entity."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: AssignedTasksCoordinator, person_id: str) -> None:
        """Initialize entity."""
        self.coordinator = coordinator
        self.person_id = person_id
        self._attr_unique_id = f"{DOMAIN}_{person_id}"
        if TodoListEntityFeature is not None:
            self._attr_supported_features = TodoListEntityFeature.UPDATE_TODO_ITEM

    @property
    def name(self) -> str | None:
        """Return entity name."""
        person = self.coordinator.store.data.people.get(self.person_id)
        if person is None:
            return "Assigned Tasks"
        return f"{person.name} Tasks"

    @property
    def available(self) -> bool:
        """Return if this entity is available."""
        person = self.coordinator.store.data.people.get(self.person_id)
        return person is not None and person.enabled

    async def async_added_to_hass(self) -> None:
        """Register update listener."""
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_UPDATED, self.async_write_ha_state
            )
        )

    async def async_get_todo_items(self) -> list[TodoItem]:
        """Return assigned tasks as To-do items."""
        items: list[TodoItem] = []
        for task in self.coordinator.tasks_for_person(self.person_id):
            task_list = self.coordinator.store.data.lists.get(task.list_id)
            description = task.description or ""
            if task_list is not None:
                description = (
                    f"List: {task_list.name}\n"
                    f"Task ID: {task.id}\n"
                    f"Completion: {'one person completes all' if task.completion_mode == MODE_ANY_ASSIGNEE else 'each person completes their own'}"
                    f"{chr(10) + description if description else ''}"
                )
            items.append(
                TodoItem(
                    summary=task.title,
                    uid=task.id,
                    status=(
                        TodoItemStatus.COMPLETED
                        if task.is_complete_for(self.person_id)
                        else TodoItemStatus.NEEDS_ACTION
                    ),
                    due=task.due_at or task.expires_at,
                    description=description,
                )
            )
        return items

    async def async_update_todo_item(self, item: TodoItem) -> None:
        """Mark a person's assignment complete or incomplete."""
        if item.uid is None:
            return
        await self.coordinator.async_complete_assignment(
            item.uid,
            self.person_id,
            item.status == TodoItemStatus.COMPLETED,
        )

    async def async_delete_todo_items(self, uids: list[str]) -> None:
        """Delete tasks from a person's card."""
        for uid in uids:
            await self.coordinator.async_delete_task(uid)


class AssignedTaskListTodoEntity(TodoListEntity):
    """A task-list To-do entity shown in Home Assistant's To-do lists UI."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: AssignedTasksCoordinator, list_id: str) -> None:
        """Initialize entity."""
        self.coordinator = coordinator
        self.list_id = list_id
        self._attr_unique_id = f"{DOMAIN}_list_{list_id}"
        if TodoListEntityFeature is not None:
            self._attr_supported_features = (
                TodoListEntityFeature.CREATE_TODO_ITEM
                | TodoListEntityFeature.DELETE_TODO_ITEM
                | TodoListEntityFeature.UPDATE_TODO_ITEM
                | TodoListEntityFeature.SET_DUE_DATETIME_ON_ITEM
                | TodoListEntityFeature.SET_DESCRIPTION_ON_ITEM
            )

    @property
    def name(self) -> str | None:
        """Return entity name."""
        task_list = self.coordinator.store.data.lists.get(self.list_id)
        if task_list is None:
            return "Assigned Task List"
        return f"{task_list.name} (Archived)" if task_list.archived else task_list.name

    @property
    def available(self) -> bool:
        """Return if this entity is available."""
        task_list = self.coordinator.store.data.lists.get(self.list_id)
        return task_list is not None and not task_list.archived

    async def async_added_to_hass(self) -> None:
        """Register update listener."""
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_UPDATED, self.async_write_ha_state
            )
        )

    async def async_get_todo_items(self) -> list[TodoItem]:
        """Return all tasks in this task list."""
        items: list[TodoItem] = []
        for task in sorted(
            self.coordinator.store.data.tasks.values(),
            key=lambda item: (
                not item.has_remaining_work(),
                item.due_at or item.expires_at or dt_util.utcnow(),
                item.title.lower(),
            ),
        ):
            if task.list_id != self.list_id:
                continue
            items.append(
                TodoItem(
                    summary=task.title,
                    uid=task.id,
                    status=(
                        TodoItemStatus.NEEDS_ACTION
                        if task.has_remaining_work()
                        else TodoItemStatus.COMPLETED
                    ),
                    due=task.due_at or task.expires_at,
                    description=_list_item_description(self.coordinator, task),
                )
            )
        return items

    async def async_create_todo_item(self, item: TodoItem) -> None:
        """Create a task from Home Assistant's To-do lists UI."""
        metadata = _parse_description_metadata(self.coordinator, item.description or "")
        assignees = metadata["assignees"] or [
            person.id for person in self.coordinator.async_person_entities()
        ]
        await self.coordinator.async_create_task(
            self.list_id,
            item.summary or "New task",
            assignees,
            description=metadata["description"],
            completion_mode=metadata["completion_mode"],
            due_at=_todo_due_as_datetime(item.due),
        )

    async def async_update_todo_item(self, item: TodoItem) -> None:
        """Update a task from Home Assistant's To-do lists UI."""
        if item.uid is None:
            return
        task = self.coordinator.store.data.tasks.get(item.uid)
        if task is None:
            return

        changes = {}
        if item.summary is not None:
            changes["title"] = item.summary
        if item.description is not None:
            metadata = _parse_description_metadata(self.coordinator, item.description)
            changes["description"] = metadata["description"]
            changes["assignees"] = metadata["assignees"] or list(task.assignees)
            changes["completion_mode"] = metadata["completion_mode"]
        due_at = _todo_due_as_datetime(item.due)
        if due_at is not None:
            changes["due_at"] = due_at
        if changes:
            await self.coordinator.async_update_task(item.uid, **changes)

        if item.status == TodoItemStatus.COMPLETED and task.has_remaining_work():
            for person_id in list(task.assignees):
                await self.coordinator.async_complete_assignment(item.uid, person_id, True)
        elif item.status == TodoItemStatus.NEEDS_ACTION and not task.has_remaining_work():
            for person_id in list(task.assignees):
                await self.coordinator.async_complete_assignment(item.uid, person_id, False)

    async def async_delete_todo_items(self, uids: list[str]) -> None:
        """Delete tasks from this task list."""
        for uid in uids:
            await self.coordinator.async_delete_task(uid)


def _list_item_description(coordinator: AssignedTasksCoordinator, task) -> str:
    """Build a readable task description for the native To-do UI."""
    people = [
        coordinator.store.data.people[person_id].name
        for person_id in task.assignees
        if person_id in coordinator.store.data.people
    ]
    completion = (
        "Any one assigned person completes it for everyone"
        if task.completion_mode == MODE_ANY_ASSIGNEE
        else "Every assigned person must complete it"
    )
    details = [
        f"Assigned people: {', '.join(people) or 'None'}",
        f"Who must complete it: {completion}",
        f"Task ID: {task.id}",
    ]
    if task.description:
        details.extend(["", task.description])
    return "\n".join(details)


def _parse_description_metadata(
    coordinator: AssignedTasksCoordinator, description: str
) -> dict:
    """Parse assignment metadata edited in Home Assistant's native To-do UI."""
    lines = description.splitlines()
    assignees: list[str] = []
    completion_mode = MODE_EACH_ASSIGNEE

    while lines and (
        lines[0].startswith("Assigned people:")
        or lines[0].startswith("Who must complete it:")
        or lines[0].startswith("Task ID:")
        or lines[0] == ""
    ):
        line = lines.pop(0)
        if line.startswith("Assigned people:"):
            assignees = _parse_people(coordinator, line.removeprefix("Assigned people:"))
        elif line.startswith("Who must complete it:"):
            value = line.removeprefix("Who must complete it:").strip().lower()
            if value.startswith("any one") or value.startswith("one"):
                completion_mode = MODE_ANY_ASSIGNEE

    return {
        "assignees": assignees,
        "completion_mode": completion_mode,
        "description": "\n".join(lines).strip(),
    }


def _parse_people(coordinator: AssignedTasksCoordinator, value: str) -> list[str]:
    """Parse comma-separated people by name or id."""
    lookup: dict[str, str] = {}
    for person_id, person in coordinator.store.data.people.items():
        lookup[person_id.lower()] = person_id
        lookup[person.name.lower()] = person_id

    people: list[str] = []
    for raw_name in value.split(","):
        person_id = lookup.get(raw_name.strip().lower())
        if person_id and person_id not in people:
            people.append(person_id)
    return people


def _todo_due_as_datetime(value) -> datetime | None:
    """Convert Home Assistant To-do due values to datetimes."""
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, time.min)
    return None
