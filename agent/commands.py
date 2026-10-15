"""Поручения голосом: «Поручи Ивановой до пятницы ответить по входящему 899».

Бот разбирает команду (исполнитель, суть, срок, входящее письмо), зачитывает её
для подтверждения и после «да» кладёт в очередь (таблица tasks в базе) — оттуда задачи
создаются в Бурмистре через Chrome (отдельный шаг).
"""
import json
import re
from datetime import date, datetime, timedelta

import pandas as pd

from . import analyze, config, db, report, sources

WEEKDAYS = ("понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье")
WEEKDAYS_GEN = ("понедельника", "вторника", "среды", "четверга", "пятницы", "субботы",
                "воскресенья")
MONTHS = ("января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа",
          "сентября", "октября", "ноября", "декабря")

# Похоже на поручение — тогда разбираем как команду (иначе это обычный вопрос).
COMMAND_RE = re.compile(r"поруч|постав\w* задач|созда\w* задач|назнач|дай задани|"
                        r"пусть\s+\w+\s+(сдела|подготов|провер|ответ|разбер)|задач\w* (для|на)\b",
                        re.I)

SCHEMA = {
    "type": "object",
    "properties": {
        "intent": {"type": "string", "enum": ["tasks", "confirm", "cancel", "other"]},
        "tasks": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "assignee": {"type": "string"},
                "text": {"type": "string"},
                "deadline": {"type": "string"},
                "letter_number": {"type": "string"},
            },
            "required": ["assignee", "text", "deadline", "letter_number"],
            "additionalProperties": False,
        }},
        "question": {"type": "string"},
    },
    "required": ["intent", "tasks", "question"],
    "additionalProperties": False,
}

PARSE_SYSTEM = """Ты разбираешь голосовые команды директора управляющей компании своему \
боту-помощнику. Текст распознан из речи автоматически и может содержать ошибки в \
фамилиях, номерах и адресах — сопоставляй со списками ниже.

Верни JSON:
- intent:
  «tasks» — директор даёт поручение(я) сотрудникам ИЛИ правит уже зачитанные ему \
поручения («срок четверг», «не Ивановой, а Петровой», «добавь ещё Сидорову…»). В этом случае \
в tasks верни ПОЛНЫЙ актуальный список поручений с учётом правки.
  «confirm» — подтверждает зачитанные поручения («да», «подтверждаю», «всё верно», «ставь»).
  «cancel» — отменяет («нет», «отмена», «не надо»).
  «other» — это не поручение, а вопрос или что-то другое.
- tasks: по одному объекту на поручение (в одной фразе их может быть несколько):
  assignee — ФИО сотрудника ТОЧНО как в списке сотрудников; если подходящего нет — \
как услышал;
  text — суть поручения коротко и по-деловому, в повелительном наклонении \
(«Подготовить ответ в ГЖИ по лицевому счёту помещения 228»);
  deadline — срок в формате ГГГГ-ММ-ДД, считая от сегодняшней даты («до пятницы» — \
ближайшая пятница, «завтра», «через неделю»); если срок не назван — пустая строка;
  letter_number — номер входящего письма из списка писем, если поручение по письму \
(назван номер или узнаётся по смыслу — «по претензии про уборку»); иначе пустая строка.
- question: если чего-то важного не хватает или неясно (например, непонятно, кому \
поручение) — короткий уточняющий вопрос директору; иначе пустая строка."""


def _staff(tables: list[sources.Table]) -> list[str]:
    """Сотрудники из выгрузок: полные ФИО из задач, иначе как в заявках и письмах."""
    names: set[str] = set()
    for t in tables:
        for col in ("Исполнители", "Исполнитель", "Автор"):
            if col in t.df.columns:
                for cell in t.df[col].dropna().astype(str):
                    for n in re.split(r",\s*|\s*\+\s*ещё\s*\d+", cell):
                        n = n.strip()
                        if len(n.split()) >= 2 and not n.startswith("nan"):
                            names.add(n)
    full = {n for n in names if len(n.split()) == 3 and "." not in n}
    # «Иванова А. Б.» не нужна, если есть «Иванова Анна Борисовна».
    short = {n for n in names - full if not any(f.split()[0] == n.split()[0] for f in full)}
    return sorted(full | short)


def _letters(tables: list[sources.Table]) -> pd.DataFrame:
    for t in tables:
        if sources.is_correspondence(t.df):
            return t.df
    return pd.DataFrame()


def _letters_brief(letters: pd.DataFrame) -> str:
    if letters.empty:
        return "нет данных"
    cols = [c for c in ("Номер входящего", "Дата документа", "Источник", "Исполнитель",
                        "Статус", "Комментарий") if c in letters.columns]
    out = letters[cols].copy()
    if "Комментарий" in out.columns:
        out["Комментарий"] = out["Комментарий"].map(lambda v: sources._short(v, 150))
    return out.to_csv(index=False)


def parse(text: str, pending: list[dict] | None) -> dict:
    r = report.latest()
    tables = r.tables() if r else []
    today = report.local_now().date()
    context = (f"Сегодня {today:%Y-%m-%d}, {WEEKDAYS[today.weekday()]}.\n\n"
               f"Сотрудники:\n" + "\n".join(_staff(tables)) + "\n\n"
               f"Входящие письма (последняя выгрузка):\n{_letters_brief(_letters(tables))}\n\n"
               "Зачитанные директору и ещё не подтверждённые поручения: "
               + (json.dumps(pending, ensure_ascii=False) if pending else "нет"))
    response = analyze.client.beta.messages.create(
        model=config.MODEL,
        max_tokens=4000,
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
        system=PARSE_SYSTEM,
        messages=[{"role": "user", "content": f"{context}\n\nКоманда директора: {text}"}],
        **analyze.FALLBACK,
    )
    analyze.log_cost("разбор поручения", [response.usage])
    return json.loads(analyze._text(response))


# ---------- Как зачитать поручение ----------

def spoken_date(iso: str) -> str:
    if not iso:
        return "без срока"
    d = date.fromisoformat(iso)
    today = report.local_now().date()
    if d == today:
        return "сегодня"
    if d == today + timedelta(days=1):
        return "завтра"
    weekday = f"{WEEKDAYS_GEN[d.weekday()]}, " if 0 < (d - today).days < 8 else ""
    return f"до {weekday}{d.day} {MONTHS[d.month - 1]}"


def letter_info(number: str) -> str:
    if not number:
        return ""
    r = report.latest()
    letters = _letters(r.tables()) if r else pd.DataFrame()
    row = letters[letters["Номер входящего"].astype(str) == str(number)] if not letters.empty else letters
    if row.empty:
        return f"по входящему номер {number}"
    row = row.iloc[0]
    what = sources._short(row.get("Комментарий", ""), 80)
    when = str(row.get("Дата документа", ""))
    try:
        d = datetime.strptime(when, "%d.%m.%Y")
        when = f" от {d.day} {MONTHS[d.month - 1]}"
    except ValueError:
        when = f" от {when}" if when else ""
    return f"по входящему номер {number}{when}" + (f": {what}" if what else "")


def confirmation(tasks: list[dict]) -> str:
    parts = []
    for i, t in enumerate(tasks, 1):
        num = f"{i}. " if len(tasks) > 1 else ""
        letter = letter_info(t["letter_number"])
        parts.append(f"{num}{t['assignee']}, {spoken_date(t['deadline'])}: {t['text']}"
                     + (f". Задача {letter}" if letter else ". Без привязки к письму"))
    head = "Ставлю задачу." if len(tasks) == 1 else f"Ставлю {len(tasks)} задачи."
    return f"{head} " + " ".join(p.rstrip(".") + "." for p in parts) + " Подтверждаете?"


# ---------- Очередь на создание в Бурмистре ----------

def letter_id(number: str) -> str:
    """Внутренний идентификатор письма в Бурмистре (нужен, чтобы открыть его карточку)."""
    if not number:
        return ""
    r = report.latest()
    letters = _letters(r.tables()) if r else pd.DataFrame()
    if letters.empty or "Идентификатор входящего" not in letters.columns:
        return ""
    row = letters[letters["Номер входящего"].astype(str) == str(number)]
    return str(row.iloc[0]["Идентификатор входящего"]).split(".")[0] if len(row) else ""


def enqueue(tasks: list[dict], source_text: str) -> list[int]:
    """Подтверждённые поручения → база (таблица tasks). Возвращает их номера."""
    return [db.add_task({**t, "letter_id": letter_id(t["letter_number"])}, source_text)
            for t in tasks]
