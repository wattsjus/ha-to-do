"""Data models for Assigned Tasks."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import uuid4

from homeassistant.util import dt as dt_util

from .const import MODE_EACH_ASSIGNEE, VALID_COMPLETION_MODES


def new_id() -> str:
    """Return a compact unique id."""
    return uuid4().hex


def utc_iso(value: datetime | None) -> str | None:
    """Serialize a datetime as UTC ISO text."""
    if value is None:
        return None
    return dt_util.as_utc(value).isoformat()


def parse_datetime(value: Any) -> datetime | None:
    """Parse a Home Assistant datetime-ish value."""
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return dt_util.as_utc(value)
    parsed = dt_util.parse_datetime(str(value))
    if parsed is None:
        raise ValueError(f"Invalid datetime: {value}")
    return dt_util.as_utc(parsed)


@dataclass(slots=True)
class Person:
    """A person who can be assigned tasks."""

    id: str
    name: str
    notify_service: str | None = None
    enabled: bool = True

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Person:
        """Deserialize a person."""
        return cls(
            id=str(data["id"]),
            name=str(data["name"]),
            notify_service=data.get("notify_service") or None,
            enabled=bool(data.get("enabled", True)),
        )

    def as_dict(self) -> dict[str, Any]:
        """Serialize a person."""
        return {
            "id": self.id,
            "name": self.name,
            "notify_service": self.notify_service,
            "enabled": self.enabled,
        }


@dataclass(slots=True)
class TaskList:
    """A task list with expiration/reset policy."""

    id: str
    name: str
    expires_at: datetime | None = None
    resets_at: datetime | None = None
    reset_interval: str | None = None
    reset_every: int = 1
    notify_before_minutes: int | None = None
    visible_to: list[str] = field(default_factory=list)
    archived: bool = False
    last_notified_at: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TaskList:
        """Deserialize a task list."""
        return cls(
            id=str(data["id"]),
            name=str(data["name"]),
            expires_at=parse_datetime(data.get("expires_at")),
            resets_at=parse_datetime(data.get("resets_at")),
            reset_interval=data.get("reset_interval") or None,
            reset_every=max(1, int(data.get("reset_every", 1) or 1)),
            notify_before_minutes=data.get("notify_before_minutes"),
            visible_to=[str(person_id) for person_id in data.get("visible_to", [])],
            archived=bool(data.get("archived", False)),
            last_notified_at=data.get("last_notified_at"),
        )

    def as_dict(self) -> dict[str, Any]:
        """Serialize a task list."""
        return {
            "id": self.id,
            "name": self.name,
            "expires_at": utc_iso(self.expires_at),
            "resets_at": utc_iso(self.resets_at),
            "reset_interval": self.reset_interval,
            "reset_every": self.reset_every,
            "notify_before_minutes": self.notify_before_minutes,
            "visible_to": list(self.visible_to),
            "archived": self.archived,
            "last_notified_at": self.last_notified_at,
        }


@dataclass(slots=True)
class Task:
    """An assigned task."""

    id: str
    list_id: str
    title: str
    description: str | None = None
    assignees: list[str] = field(default_factory=list)
    completion_mode: str = MODE_EACH_ASSIGNEE
    due_at: datetime | None = None
    expires_at: datetime | None = None
    resets_at: datetime | None = None
    reset_interval: str | None = None
    reset_every: int = 1
    weekly_days: list[str] = field(default_factory=list)
    notify_before_minutes: int | None = None
    visible_to: list[str] = field(default_factory=list)
    completed_by: dict[str, str] = field(default_factory=dict)
    last_notified_at: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Task:
        """Deserialize a task."""
        completion_mode = data.get("completion_mode", MODE_EACH_ASSIGNEE)
        if completion_mode not in VALID_COMPLETION_MODES:
            completion_mode = MODE_EACH_ASSIGNEE
        return cls(
            id=str(data["id"]),
            list_id=str(data["list_id"]),
            title=str(data["title"]),
            description=data.get("description") or None,
            assignees=[str(person_id) for person_id in data.get("assignees", [])],
            completion_mode=completion_mode,
            due_at=parse_datetime(data.get("due_at")),
            expires_at=parse_datetime(data.get("expires_at")),
            resets_at=parse_datetime(data.get("resets_at")),
            reset_interval=data.get("reset_interval") or None,
            reset_every=max(1, int(data.get("reset_every", 1) or 1)),
            weekly_days=[str(day) for day in data.get("weekly_days", [])],
            notify_before_minutes=data.get("notify_before_minutes"),
            visible_to=[str(person_id) for person_id in data.get("visible_to", [])],
            completed_by=dict(data.get("completed_by", {})),
            last_notified_at=data.get("last_notified_at"),
        )

    def as_dict(self) -> dict[str, Any]:
        """Serialize a task."""
        return {
            "id": self.id,
            "list_id": self.list_id,
            "title": self.title,
            "description": self.description,
            "assignees": list(self.assignees),
            "completion_mode": self.completion_mode,
            "due_at": utc_iso(self.due_at),
            "expires_at": utc_iso(self.expires_at),
            "resets_at": utc_iso(self.resets_at),
            "reset_interval": self.reset_interval,
            "reset_every": self.reset_every,
            "weekly_days": list(self.weekly_days),
            "notify_before_minutes": self.notify_before_minutes,
            "visible_to": list(self.visible_to),
            "completed_by": dict(self.completed_by),
            "last_notified_at": self.last_notified_at,
        }

    def is_complete_for(self, person_id: str) -> bool:
        """Return if this task is complete for a person."""
        if self.completion_mode != MODE_EACH_ASSIGNEE:
            return bool(self.completed_by)
        return person_id in self.completed_by

    def has_remaining_work(self) -> bool:
        """Return if the task has any remaining assignee work."""
        if self.completion_mode != MODE_EACH_ASSIGNEE:
            return not self.completed_by
        return any(person_id not in self.completed_by for person_id in self.assignees)
