"""Единый формат данных о компании.

Любой источник (мок-данные, CRM без API, 1С) приводится к этим структурам,
а отчёт строится уже из них — поэтому новые источники не меняют логику отчёта.
"""
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

OPEN_STATUSES = ("new", "in_progress")
STATUS_NAMES = {"new": "новая", "in_progress": "в работе", "done": "выполнена",
                "postponed": "отложена"}


@dataclass
class Department:
    id: str
    name: str
    head: str


@dataclass
class Employee:
    name: str
    position: str
    department: str


@dataclass
class House:
    id: str
    address: str


@dataclass
class Task:
    id: str
    title: str
    category: str
    department: str
    assignee: str
    house: str | None
    status: str
    priority: str
    created: datetime
    deadline: datetime | None
    closed: datetime | None
    source: str
    note: str = ""
    decision: str = ""  # что должен решить руководитель

    @property
    def is_open(self) -> bool:
        return self.status in OPEN_STATUSES

    def is_overdue(self, now: datetime) -> bool:
        return self.is_open and self.deadline is not None and self.deadline < now


@dataclass
class HouseFinance:
    house: str
    charged: float
    paid: float

    @property
    def rate(self) -> float:
        return self.paid / self.charged if self.charged else 1.0


@dataclass
class Company:
    name: str
    as_of: datetime
    departments: list[Department]
    employees: list[Employee]
    houses: list[House]
    tasks: list[Task]
    finance_period: str = ""
    finance: list[HouseFinance] = field(default_factory=list)

    def department(self, dep_id: str) -> Department:
        return next(d for d in self.departments if d.id == dep_id)

    def address(self, house_id: str | None) -> str:
        if house_id is None:
            return "—"
        return next((h.address for h in self.houses if h.id == house_id), house_id)


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def load(path: Path) -> Company:
    raw = json.loads(path.read_text(encoding="utf-8"))
    tasks = [Task(**{**t, "created": _dt(t["created"]), "deadline": _dt(t.get("deadline")),
                     "closed": _dt(t.get("closed"))}) for t in raw["tasks"]]
    fin = raw.get("finance", {})
    return Company(
        name=raw["company"],
        as_of=_dt(raw["as_of"]),
        departments=[Department(**d) for d in raw["departments"]],
        employees=[Employee(**e) for e in raw["employees"]],
        houses=[House(**h) for h in raw["houses"]],
        tasks=tasks,
        finance_period=fin.get("period", ""),
        finance=[HouseFinance(**f) for f in fin.get("houses", [])],
    )
