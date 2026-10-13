"""Отчёт по правилам (без нейросети): «красные точки», короткий текст для голоса,
полный отчёт с деталями и ответы на запрос «подробнее про …»."""
from dataclasses import dataclass
from datetime import datetime, timedelta

from .company import STATUS_NAMES, Company, Task

MONTHS = ("января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа",
          "сентября", "октября", "ноября", "декабря")
REPEAT_DAYS, REPEAT_MIN = 14, 3   # повторные заявки: от 3 по одному дому и теме за 14 дней
OVERLOAD_OPEN = 4                 # перегрузка: от 4 открытых задач у сотрудника
COLLECTION_NORM = 0.85            # собираемость платежей ниже 85% — тревожно
SHORT_FLAGS = 6                   # сколько красных точек озвучивать


@dataclass
class Flag:
    order: int   # чем меньше, тем важнее
    spoken: str  # фраза для голосового отчёта
    written: str  # строка для полного отчёта


@dataclass
class Digest:
    short: str
    full: str
    flags: list[Flag]


# ---------- мелкие помощники ----------

def plural(n: int, forms: tuple[str, str, str]) -> str:
    n100, n10 = abs(n) % 100, abs(n) % 10
    if 11 <= n100 <= 14:
        form = forms[2]
    elif n10 == 1:
        form = forms[0]
    elif 2 <= n10 <= 4:
        form = forms[1]
    else:
        form = forms[2]
    return f"{n} {form}"


TASKS = ("задача", "задачи", "задач")
DAYS = ("день", "дня", "дней")
HOURS = ("час", "часа", "часов")


def lower_first(s: str) -> str:
    return s[:1].lower() + s[1:]


def surname(name: str) -> str:
    return name.split()[0]


def spoken_date(dt: datetime) -> str:
    return f"{dt.day} {MONTHS[dt.month - 1]}"


def late_by(task: Task, now: datetime) -> str:
    delta = now - task.deadline
    if delta.days >= 1:
        return plural(delta.days, DAYS)
    return plural(max(1, int(delta.total_seconds() // 3600)), HOURS)


def money(x: float) -> str:
    return f"{x:,.0f}".replace(",", " ") + " ₽"


def greeting(now: datetime) -> str:
    if now.hour < 12:
        return "Доброе утро"
    if now.hour < 18:
        return "Добрый день"
    return "Добрый вечер"


# ---------- красные точки ----------

def find_flags(c: Company) -> list[Flag]:
    now = c.as_of
    flags: list[Flag] = []
    mentioned: set[str] = set()
    open_tasks = [t for t in c.tasks if t.is_open]

    # 1. Срочные (аварийные) открытые задачи.
    for t in sorted(open_tasks, key=lambda t: t.deadline or now):
        if t.priority == "high" and not t.decision:
            note = f", {t.note}" if t.note else ""
            late = f", срок прошёл {late_by(t, now)} назад" if t.is_overdue(now) else ""
            flags.append(Flag(1, f"{c.address(t.house)}: {lower_first(t.title)}{note}{late}.",
                              f"🔴 Срочно — {c.address(t.house)}: {t.title} ({t.id}, "
                              f"{t.assignee}){note}{late}"))
            mentioned.add(t.id)

    # 2. Где нужно решение руководителя.
    decisions = [t for t in open_tasks if t.decision]
    if decisions:
        items = "; ".join(t.decision for t in decisions)
        flags.append(Flag(2, f"Нужно ваше решение: {items}.",
                          "🟠 Нужно решение руководителя:\n" + "\n".join(
                              f"   - {t.decision} ({t.id}, срок {t.deadline:%d.%m})"
                              for t in decisions)))
        mentioned.update(t.id for t in decisions)

    # 3. Просроченные задачи (кроме уже названных).
    overdue = sorted((t for t in open_tasks if t.is_overdue(now) and t.id not in mentioned),
                     key=lambda t: t.deadline)
    if overdue:
        worst = overdue[0]
        flags.append(Flag(3, f"Просрочено ещё {plural(len(overdue), TASKS)}. Дольше всех — "
                             f"«{lower_first(worst.title)}» по дому {c.address(worst.house)}, "
                             f"на {late_by(worst, now)}, исполнитель {surname(worst.assignee)}.",
                          f"🟠 Просрочено {plural(len(overdue), TASKS)}: " + ", ".join(
                              f"{t.id} (на {late_by(t, now)})" for t in overdue)))

    # 4. Повторные заявки по одному дому и теме.
    since = now - timedelta(days=REPEAT_DAYS)
    groups: dict[tuple[str, str], list[Task]] = {}
    for t in c.tasks:
        if t.house and t.created >= since:
            groups.setdefault((t.house, t.category), []).append(t)
    for (house, cat), items in groups.items():
        if len(items) >= REPEAT_MIN:
            flags.append(Flag(4, f"По дому {c.address(house)} уже "
                                 f"{plural(len(items), ('заявка', 'заявки', 'заявок'))} по теме "
                                 f"«{cat}» за две недели — похоже на системную проблему.",
                              f"🟡 Повторные заявки — {c.address(house)}, «{cat}»: "
                              + ", ".join(t.id for t in items)))

    # 5. Перегруженные сотрудники.
    for e in c.employees:
        mine = [t for t in open_tasks if t.assignee == e.name]
        late = [t for t in mine if t.is_overdue(now)]
        if len(mine) >= OVERLOAD_OPEN:
            flags.append(Flag(5, f"{e.position.capitalize()} {surname(e.name)}: "
                                 f"{plural(len(mine), ('открытая задача', 'открытые задачи', 'открытых задач'))}"
                                 f", из них просрочено {len(late)}. Возможно, нужна помощь.",
                              f"🟡 Перегрузка — {e.name} ({e.position}): открыто {len(mine)}, "
                              f"просрочено {len(late)}"))

    # 6. Собираемость платежей (1С).
    for f in c.finance:
        if f.rate < COLLECTION_NORM:
            flags.append(Flag(6, f"Собираемость платежей по дому {c.address(f.house)} за "
                                 f"{c.finance_period.split()[0]} — "
                                 f"{plural(round(f.rate * 100), ('процент', 'процента', 'процентов'))}"
                                 ", это ниже нормы.",
                              f"🟡 Низкая собираемость — {c.address(f.house)}: {f.rate:.0%} "
                              f"(недобор {money(f.charged - f.paid)})"))

    return sorted(flags, key=lambda f: f.order)


# ---------- короткий текст для голоса ----------

def short_text(c: Company, flags: list[Flag]) -> str:
    now = c.as_of
    open_tasks = [t for t in c.tasks if t.is_open]
    overdue = [t for t in open_tasks if t.is_overdue(now)]
    day_ago = now - timedelta(days=1)
    created = sum(t.created >= day_ago for t in c.tasks)
    closed = sum(bool(t.closed and t.closed >= day_ago) for t in c.tasks)

    parts = [f"{greeting(now)}! Сводка по компании на {spoken_date(now)}, {now:%H:%M}."]
    if flags:
        parts.append("Сначала главное.")
        for i, f in enumerate(flags[:SHORT_FLAGS]):
            prefix = ("Первое", "Второе", "Третье", "Четвёртое", "Пятое", "Шестое")[i]
            parts.append(f"{prefix}. {f.spoken}")
        if len(flags) > SHORT_FLAGS:
            parts.append(f"И ещё {len(flags) - SHORT_FLAGS} замечания — в полном отчёте.")
    else:
        parts.append("Тревожных моментов нет.")
    parts.append(f"В целом: в работе {plural(len(open_tasks), TASKS)}, просрочено "
                 f"{len(overdue)}. За сутки поступило {created}, закрыто {closed}.")
    parts.append("Полный отчёт сохранён. Можете спросить подробности по любому отделу, "
                 "сотруднику или дому.")
    return "\n".join(parts)


# ---------- полный отчёт ----------

def task_line(c: Company, t: Task) -> str:
    mark = " ⚠️ просрочена" if t.is_overdue(c.as_of) else ""
    due = f", срок {t.deadline:%d.%m %H:%M}" if t.deadline else ""
    closed = f", закрыта {t.closed:%d.%m %H:%M}" if t.closed else ""
    note = f" — {t.note}" if t.note else ""
    return (f"- **{t.id}** {t.title} | {c.address(t.house)} | {t.assignee} | "
            f"{STATUS_NAMES[t.status]}{due}{closed}{mark}{note}")


def full_text(c: Company, flags: list[Flag]) -> str:
    now = c.as_of
    open_tasks = [t for t in c.tasks if t.is_open]
    out = [f"# Отчёт: {c.name}", f"Состояние на {now:%d.%m.%Y %H:%M}", ""]

    out += ["## 1. Красные точки", ""]
    out += [f"- {f.written}" for f in flags] or ["Тревожных моментов нет."]

    out += ["", "## 2. Общие цифры", "",
            f"- Всего задач в выборке: {len(c.tasks)}",
            f"- Открыто: {len(open_tasks)}, из них просрочено: "
            f"{sum(t.is_overdue(now) for t in open_tasks)}",
            f"- Выполнено: {sum(t.status == 'done' for t in c.tasks)}, "
            f"отложено: {sum(t.status == 'postponed' for t in c.tasks)}"]

    out += ["", "## 3. По отделам", "",
            "| Отдел | Руководитель | Открыто | Просрочено | Выполнено |",
            "|---|---|---|---|---|"]
    for d in c.departments:
        ts = [t for t in c.tasks if t.department == d.id]
        out.append(f"| {d.name} | {d.head} | {sum(t.is_open for t in ts)} | "
                   f"{sum(t.is_overdue(now) for t in ts)} | {sum(t.status == 'done' for t in ts)} |")

    out += ["", "## 4. По сотрудникам", "",
            "| Сотрудник | Должность | Отдел | Открыто | Просрочено | Выполнено |",
            "|---|---|---|---|---|---|"]
    for e in c.employees:
        ts = [t for t in c.tasks if t.assignee == e.name]
        out.append(f"| {e.name} | {e.position} | {c.department(e.department).name} | "
                   f"{sum(t.is_open for t in ts)} | {sum(t.is_overdue(now) for t in ts)} | "
                   f"{sum(t.status == 'done' for t in ts)} |")

    out += ["", "## 5. По домам", "",
            "| Дом | Задач всего | Открыто | Просрочено | Собираемость |",
            "|---|---|---|---|---|"]
    fin = {f.house: f for f in c.finance}
    for h in c.houses:
        ts = [t for t in c.tasks if t.house == h.id]
        rate = f"{fin[h.id].rate:.0%}" if h.id in fin else "—"
        out.append(f"| {h.address} | {len(ts)} | {sum(t.is_open for t in ts)} | "
                   f"{sum(t.is_overdue(now) for t in ts)} | {rate} |")

    if c.finance:
        out += ["", f"## 6. Платежи жителей ({c.finance_period}, из 1С)", "",
                "| Дом | Начислено | Оплачено | Недобор | Собираемость |", "|---|---|---|---|---|"]
        for f in c.finance:
            out.append(f"| {c.address(f.house)} | {money(f.charged)} | {money(f.paid)} | "
                       f"{money(f.charged - f.paid)} | {f.rate:.0%} |")

    out += ["", "## 7. Все открытые задачи", ""]
    out += [task_line(c, t) for t in sorted(open_tasks, key=lambda t: t.deadline or now)]
    return "\n".join(out) + "\n"


def build(c: Company) -> Digest:
    flags = find_flags(c)
    return Digest(short_text(c, flags), full_text(c, flags), flags)


# ---------- «подробнее про …» ----------

def details(c: Company, query: str) -> str:
    """Детали по отделу, сотруднику или дому. Ищет по части названия, фамилии, адреса."""
    q = query.lower().strip()
    now = c.as_of
    sections = []

    for d in c.departments:
        if q in d.name.lower() or q == d.id:
            ts = [t for t in c.tasks if t.department == d.id]
            staff = ", ".join(f"{e.name} ({e.position})" for e in c.employees if e.department == d.id)
            sections.append(f"## Отдел: {d.name}\nРуководитель: {d.head}\nСотрудники: {staff}\n\n"
                            + "\n".join(task_line(c, t) for t in ts))

    for e in c.employees:
        if q in e.name.lower():
            ts = [t for t in c.tasks if t.assignee == e.name]
            late = sum(t.is_overdue(now) for t in ts)
            sections.append(f"## Сотрудник: {e.name}, {e.position} "
                            f"({c.department(e.department).name})\n"
                            f"Открыто: {sum(t.is_open for t in ts)}, просрочено: {late}, "
                            f"выполнено: {sum(t.status == 'done' for t in ts)}\n\n"
                            + "\n".join(task_line(c, t) for t in ts))

    for h in c.houses:
        if q in h.address.lower():
            ts = [t for t in c.tasks if t.house == h.id]
            fin = next((f for f in c.finance if f.house == h.id), None)
            money_line = (f"Платежи за {c.finance_period}: начислено {money(fin.charged)}, "
                          f"оплачено {money(fin.paid)}, собираемость {fin.rate:.0%}\n"
                          if fin else "")
            sections.append(f"## Дом: {h.address}\n{money_line}\n"
                            + "\n".join(task_line(c, t) for t in ts))

    for t in c.tasks:
        if q == t.id.lower():
            sections.append(f"## Задача {t.id}\n{task_line(c, t)}"
                            + (f"\nНужно решение: {t.decision}" if t.decision else ""))

    return "\n\n".join(sections) or (f"По запросу «{query}» ничего не нашёл. Попробуйте фамилию, "
                                     "часть названия отдела, улицу или номер задачи.")
