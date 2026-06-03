"""Persistence for Assigned Tasks."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import STORAGE_KEY, STORAGE_VERSION
from .models import Person, Task, TaskList


@dataclass(slots=True)
class AssignedTasksData:
    """All persisted integration data."""

    people: dict[str, Person] = field(default_factory=dict)
    lists: dict[str, TaskList] = field(default_factory=dict)
    tasks: dict[str, Task] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> AssignedTasksData:
        """Deserialize stored data."""
        if not data:
            return cls()
        return cls(
            people={
                person_id: Person.from_dict(person)
                for person_id, person in data.get("people", {}).items()
            },
            lists={
                list_id: TaskList.from_dict(task_list)
                for list_id, task_list in data.get("lists", {}).items()
            },
            tasks={
                task_id: Task.from_dict(task)
                for task_id, task in data.get("tasks", {}).items()
            },
        )

    def as_dict(self) -> dict[str, Any]:
        """Serialize stored data."""
        return {
            "people": {
                person_id: person.as_dict()
                for person_id, person in sorted(self.people.items())
            },
            "lists": {
                list_id: task_list.as_dict()
                for list_id, task_list in sorted(self.lists.items())
            },
            "tasks": {
                task_id: task.as_dict()
                for task_id, task in sorted(self.tasks.items())
            },
        }


class AssignedTasksStore:
    """Home Assistant storage wrapper."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize storage."""
        self._store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self.data = AssignedTasksData()

    async def async_load(self) -> AssignedTasksData:
        """Load data from storage."""
        self.data = AssignedTasksData.from_dict(await self._store.async_load())
        return self.data

    async def async_save(self) -> None:
        """Persist data to storage."""
        await self._store.async_save(self.data.as_dict())
