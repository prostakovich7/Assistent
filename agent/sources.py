"""Чтение выгрузок из Бурмистра (Excel/CSV) из папки data/inbox.

Для выгрузки заявок Бурмистра (есть колонки «Статус», «Дата создания»,
«Исполнитель») агент сам считает статистику по всей таблице, а на анализ
отдаёт только открытые заявки и то, что изменилось за последние сутки.
Другие таблицы передаются как есть.
Персональные данные жильцов удаляются до любой обработки.
"""
import html
import re
import shutil
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

from . import config

# Колонки с персональными данными жильцов — удаляются целиком.
PERSONAL_COLUMNS = ("фио", "заявител", "телефон", "тел.", "e-mail", "email", "почта",
                    "собственник", "житель", "контакт", "абонент", "л/с", "лицев")
# Колонки, бесполезные для анализа.
NOISE_COLUMNS = ("файлы", "id")
# Телефоны и почта внутри текста (описания заявок, комментарии):
# 10–11 цифр подряд или через пробелы/дефисы/скобки; местные вида 45-67-89; e-mail.
PHONE_RE = re.compile(r"(?<![\d.:])\+?\d(?:[\s\-()]*\d){9,10}(?![\d.:])"
                      r"|(?<![\d.:])\d{2,3}-\d{2}-\d{2}(?![\d.:])"
                      r"|\d{9,}")  # любые длинные номера: телефоны, ИНН, лицевые счета
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
# Улица и дом из полного адреса: «…, ул Тореза, д. 24, кв. 118» → «ул Тореза 24».
HOUSE_RE = re.compile(r"((?:ул|пр-кт|пр|пер|б-р|ш|пл|проезд)\.?\s+[^,]+),\s*д\.?\s*([\w/]+)", re.I)
FLAT_RE = re.compile(r"кв\.?\s*(\w+)", re.I)

FILE_PATTERNS = ("*.xlsx", "*.xls", "*.csv")
CLOSED = ("закрыта", "отменена", "выполнена")
TEXT_LIMIT = 300  # сколько знаков текста заявки передавать на анализ
REPEAT_DAYS, REPEAT_MIN = 14, 3  # «повторные заявки»: от 3 по одному дому за 14 дней
# Массовые отключения: заявки за 48 часов со словами про отключение/весь дом
# или от 3 однотипных заявок по одному дому.
OUTAGE_HOURS, OUTAGE_SAME_HOUSE = 48, 3
OUTAGE_RE = re.compile(
    r"нет\s+(?:света|электр|воды|холодн|горяч|отоплен|тепла|газа)|отключ|"
    r"весь\s+дом|всём\s+доме|всем\s+доме|по\s+всему\s+дому|во\s+всех\s+подъезд|"
    r"холодные\s+батаре|не\s+греют", re.I)


@dataclass
class Table:
    name: str
    df: pd.DataFrame  # уже без персональных данных


def find_files() -> list[Path]:
    files = []
    for pattern in FILE_PATTERNS:
        files.extend(config.INBOX.glob(pattern))
    return sorted(f for f in files if not f.name.startswith("~$"))


def read_table(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".csv":
        for enc in ("utf-8-sig", "cp1251"):
            try:
                return pd.read_csv(path, sep=None, engine="python", encoding=enc)
            except UnicodeDecodeError:
                continue
        raise ValueError(f"Не удалось прочитать {path.name}")
    return pd.read_excel(path)


def clean_text(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html.unescape(text)).replace("\xa0", " ")
    return PHONE_RE.sub("[телефон]", EMAIL_RE.sub("[почта]", text))


def anonymize(df: pd.DataFrame) -> pd.DataFrame:
    keep = [c for c in df.columns
            if not any(p in str(c).lower() for p in PERSONAL_COLUMNS)
            and str(c).lower() not in NOISE_COLUMNS
            and df[c].nunique(dropna=True) > 1]  # пустые и одинаковые во всех строках
    df = df[keep].copy()
    for col in df.columns:
        if not pd.api.types.is_numeric_dtype(df[col]):
            df[col] = df[col].map(lambda v: "" if pd.isna(v) else clean_text(str(v)))
    return df


def load() -> tuple[list[Table], list[Path]]:
    files = find_files()
    tables = []
    for f in files:
        df = anonymize(read_table(f))
        if is_tasks_raw(df):
            df = parse_tasks(df)
        tables.append(Table(f.stem, df))
    return tables, files


# ---------- Реестр задач директора (Бурмистр) ----------
# Одна задача занимает несколько строк: первая — номер, название, срок, автор;
# ниже — дополнительные исполнители и лента комментариев. Время — по UTC.

TASK_DONE = ("выполнена", "закрыта", "завершена", "отменена")
TASK_REVIEW = "ожидает проверки"
GOV_RE = re.compile(
    r"жилинспекц|\bгжи\b|госжилнадзор|прокурат|администрац|роспотребнадзор|\bсуд\w*\b|"
    r"\bеддс\b|мчс|предписани|депутат|\bфас\b|ростехнадзор|министерств|налогов|"
    r"полици|\bовд\b|\bумвд\b|росреестр|фонд\s+капремонт|ркц", re.I)


def is_tasks_raw(df: pd.DataFrame) -> bool:
    return {"№ задачи", "Дедлайн", "Исполнитель"} <= set(df.columns)


def is_tasks(df: pd.DataFrame) -> bool:
    return {"Номер задачи", "Дедлайн", "Исполнители"} <= set(df.columns)


def _utc_to_local(values: pd.Series) -> pd.Series:
    dt = pd.to_datetime(values.replace("", None), errors="coerce")
    return dt.dt.tz_localize("UTC").dt.tz_convert(config.TIMEZONE).dt.tz_localize(None)


def _next_col(df: pd.DataFrame, name: str) -> str | None:
    """Безымянная колонка сразу за заголовком (у Бурмистра там «Просмотрено»/«Текст»)."""
    cols = list(df.columns)
    i = cols.index(name) + 1 if name in cols else len(cols)
    return cols[i] if i < len(cols) and str(cols[i]).startswith("Unnamed") else None


def parse_tasks(df: pd.DataFrame) -> pd.DataFrame:
    viewed_col = _next_col(df, "Исполнитель")
    comment_col = _next_col(df, "Комментарии")
    df = df[df["Исполнитель"].astype(str) != "ФИО"].copy()  # строка подзаголовков
    df["_id"] = df["№ задачи"].ffill()
    df = df[df["_id"].notna()]

    tasks = []
    for task_id, g in df.groupby("_id", sort=False):
        first = g.iloc[0]
        people = [p for p in g["Исполнитель"].astype(str) if p.strip()]
        comments = []
        if comment_col:
            dates = _utc_to_local(g["Комментарии"].astype(str))
            for d, text in zip(dates, g[comment_col].astype(str)):
                if text.strip():
                    stamp = f"{d:%d.%m %H:%M}" if pd.notna(d) else ""
                    comments.append(f"[{stamp}] {_short(text, 400)}")
        viewed = (g[viewed_col].astype(str).str.strip() != "").sum() if viewed_col else None
        tasks.append({
            "Номер задачи": int(task_id),
            "Название": str(first.get("Название задачи", "")).strip(),
            "Статус": str(first.get("Статус", "")).strip(),
            "Создана": first.get("Дата создания", ""),
            "Дедлайн": first.get("Дедлайн", ""),
            "Адрес": short_address(str(first.get("Адрес", ""))) if first.get("Адрес") else "",
            "Автор": str(first.get("Автор", "")).strip(),
            "Исполнители": ", ".join(people),
            "Просмотрели": f"{viewed} из {len(people)}" if viewed is not None else "",
            "Текст задачи": _short(first.get("Текст задачи", ""), 500),
            "Комментариев": len(comments),
            "Последний комментарий": comments[-1] if comments else "",
            "Комментарии": " | ".join(comments),
        })
    out = pd.DataFrame(tasks)
    for c in ("Создана", "Дедлайн"):
        out[c] = _utc_to_local(out[c].astype(str)).dt.strftime("%d.%m.%Y %H:%M")
    return out


def summarize_tasks(df: pd.DataFrame, now: datetime) -> str:
    df = df.copy()
    status = df["Статус"].str.lower()
    deadline = pd.to_datetime(df["Дедлайн"], dayfirst=True, errors="coerce")
    df["_открыта"] = ~status.isin(TASK_DONE) & (status != TASK_REVIEW)
    df["_просрочена"] = df["_открыта"] & (deadline < now)
    df["_дней просрочки"] = ((now - deadline).dt.total_seconds() / 86400).round(1)
    text = df["Название"] + " " + df["Текст задачи"] + " " + df["Комментарии"]
    df["_госорган"] = text.str.contains(GOV_RE)

    review = status == TASK_REVIEW
    df["Госорган"] = df["_госорган"].map({True: "да", False: ""})
    lines = [f"Ждут проверки директора: {review.sum()}. Просрочено: {df['_просрочена'].sum()}."]

    ex = (df.assign(Исполнитель=df["Исполнители"].str.split(r",\s*"))
          .explode("Исполнитель", ignore_index=True))
    ex = ex[ex["Исполнитель"].str.len() > 0]
    staff = pd.DataFrame({
        "ждут проверки": ex[ex["Статус"].str.lower() == TASK_REVIEW].groupby("Исполнитель").size(),
        "просрочено": ex[ex["_просрочена"]].groupby("Исполнитель").size(),
    }).fillna(0).astype(int).sort_values(["просрочено", "ждут проверки"], ascending=False)
    lines.append("### По сотрудникам\n" + staff.to_csv())

    cols = ["Номер задачи", "Название", "Статус", "Создана", "Дедлайн", "_дней просрочки",
            "Исполнители", "Госорган", "Адрес", "Текст задачи", "Комментариев", "Комментарии"]
    view = lambda d: d[cols].rename(columns={"_дней просрочки": "Дней после срока"}).to_csv(index=False)

    waiting = df[review].sort_values("_дней просрочки", ascending=False)
    lines.append(f"### Ждут проверки директора ({len(waiting)}) — сотрудники ждут решения; "
                 "в комментариях промежуточные результаты\n" + (view(waiting) if len(waiting) else "нет"))
    overdue = df[df["_просрочена"]].sort_values("_дней просрочки", ascending=False)
    lines.append(f"### Просроченные ({len(overdue)})\n" + (view(overdue) if len(overdue) else "нет"))
    return "\n\n".join(lines)


# ---------- Входящая корреспонденция (Бурмистр, CSV) ----------

CORR_DONE = ("отвечено", "выполнена", "закрыта", "отменена", "архив")
# Пометка директора «СМ» в начале комментария («СМ.... От: …») — письмо просмотрено,
# действий не нужно. Латинские CM — на случай английской раскладки.
SEEN_RE = re.compile(r"^\s*(см|cm)(?![а-яa-z])", re.I)
GOV_CORR_RE = re.compile(GOV_RE.pattern + r"|\bусзн\b|соцзащит|gosgil|госжил|\bгу\b|мвд|\bмфц\b",
                         re.I)
MONEY_RE = re.compile(
    r"претензи|\bиск\b|исков|суд|неустойк|штраф|пен[яи]\b|задолж|долг|взыска|компенсац|"
    r"ущерб|возмещ|оплат|счёт|счет\b|счета|акт\w* сверк|расторж|перерасч|стоимост|смет", re.I)


def is_correspondence(df: pd.DataFrame) -> bool:
    return {"Номер входящего", "Дата документа", "Статус"} <= set(df.columns)


def _corr_flags(df: pd.DataFrame, now: datetime) -> pd.DataFrame:
    df = df.copy()
    status = df["Статус"].astype(str).str.lower()
    comment = df.get("Комментарий", pd.Series("", index=df.index)).astype(str)
    source = df.get("Источник", pd.Series("", index=df.index)).astype(str)
    due = pd.to_datetime(df.get("Срок ответа"), dayfirst=True, errors="coerce")
    df["_дата"] = pd.to_datetime(df["Дата документа"], dayfirst=True, errors="coerce")
    df["_см"] = comment.str.contains(SEEN_RE)
    df["_закрыто"] = status.isin(CORR_DONE)
    df["_без исполнителя"] = df.get("Исполнитель", "").astype(str).str.strip().isin(["", "nan"])
    df["_просрочено"] = ~df["_закрыто"] & ~df["_см"] & (due < now)
    text = source + " " + comment
    df["_госорган"] = text.str.contains(GOV_CORR_RE)
    df["_деньги"] = text.str.contains(MONEY_RE)
    return df


def summarize_correspondence(df: pd.DataFrame, now: datetime) -> str:
    df = _corr_flags(df, now)
    need = ~df["_см"]  # письма с пометкой «СМ» действий не требуют
    no_exec = df[need & df["_без исполнителя"] & ~df["_закрыто"]]
    no_answer = df[need & ~df["_закрыто"]]
    lines = [
        f"Входящих писем: {len(df)}, из них с пометкой директора «СМ» (действий не нужно): "
        f"{df['_см'].sum()}.",
        f"Без назначенного исполнителя (кроме «СМ»): {len(no_exec)}. "
        f"Не отвечено / не закрыто (кроме «СМ»): {len(no_answer)}. "
        f"Срок ответа прошёл: {df['_просрочено'].sum()}.",
        "Статусы: " + ", ".join(f"{k}: {v}" for k, v in df["Статус"].value_counts().items()),
    ]
    cols = [c for c in ("Номер входящего", "Дата документа", "Источник", "Способ получения",
                        "Исполнитель", "Срок ответа", "Статус", "Комментарий") if c in df.columns]

    def view(d: pd.DataFrame) -> str:
        out = d[cols].copy()
        if "Комментарий" in out.columns:
            out["Комментарий"] = out["Комментарий"].map(lambda v: _short(v, 400))
        out["СМ"] = d["_см"].map({True: "да", False: ""})
        return out.to_csv(index=False)

    for title, mask in (("Запросы и письма госорганов", df["_госорган"]),
                        ("Претензии и финансовые риски (найдено по словам — проверь по смыслу)",
                         df["_деньги"]),
                        ("Без исполнителя (кроме «СМ»)", need & df["_без исполнителя"] & ~df["_закрыто"]),
                        ("Срок ответа прошёл", df["_просрочено"])):
        part = df[mask]
        lines.append(f"### {title} ({len(part)})\n" + (view(part) if len(part) else "нет"))
    lines.append(f"### Все входящие за период ({len(df)})\n" + view(df))
    return "\n\n".join(lines)


# ---------- Заявки Бурмистра ----------

def is_requests(df: pd.DataFrame) -> bool:
    return {"Статус", "Дата создания", "Исполнитель", "Адрес"} <= set(df.columns)


def short_address(addr: str) -> str:
    m = HOUSE_RE.search(addr)
    if not m:
        return addr
    street = re.sub(r"\.", "", m.group(1)).strip()
    flat = FLAT_RE.search(addr[m.end():])
    return f"{street} {m.group(2)}" + (f", кв {flat.group(1)}" if flat else "")


def prepare_requests(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["Адрес"] = df["Адрес"].map(short_address)
    df["Дом"] = df["Адрес"].str.replace(r",\s*кв.*$", "", regex=True).str.lower()
    df["_создана"] = pd.to_datetime(df["Дата создания"], dayfirst=True, errors="coerce")
    if "Дата закрытия" in df.columns:
        df["_закрыта"] = pd.to_datetime(df["Дата закрытия"], dayfirst=True, errors="coerce")
    else:
        df["_закрыта"] = pd.NaT
    df["_открыта"] = ~df["Статус"].str.lower().isin(CLOSED)
    return df


def _short(text, limit=TEXT_LIMIT) -> str:
    text = re.sub(r"\s+", " ", str(text)).strip()
    return text if len(text) <= limit else text[:limit] + "…"


def _rows(df: pd.DataFrame, now: datetime) -> str:
    cols = [c for c in ("Номер", "Дата создания", "Адрес", "Тип заявки", "Статус",
                        "Исполнитель", "Кем создана", "Текст заявки", "Дата закрытия",
                        "Текст результата", "Комментарии") if c in df.columns]
    out = df[cols].copy()
    for c in ("Текст заявки", "Текст результата", "Комментарии"):
        if c in out.columns:
            out[c] = out[c].map(_short)
    out.insert(3, "Дней с создания", ((now - df["_создана"]).dt.total_seconds() / 86400).round(1))
    return out.to_csv(index=False)


def outages(df: pd.DataFrame, now: datetime) -> str:
    """Признаки отключений на весь дом за последние двое суток."""
    recent = df[df["_создана"] >= now - timedelta(hours=OUTAGE_HOURS)]
    text = recent["Текст заявки"].fillna("") if "Текст заявки" in recent.columns else ""
    by_words = recent[text.str.contains(OUTAGE_RE)] if len(recent) else recent
    head = f"### Возможные массовые отключения (за {OUTAGE_HOURS} ч)\n"

    kind = "Тип заявки" if "Тип заявки" in recent.columns else None
    keys = ["Дом", kind] if kind else ["Дом"]
    groups = recent.groupby(keys).agg(заявок=("Номер", "size"),
                                      номера=("Номер", lambda s: ", ".join(map(str, s))))
    groups = groups[groups["заявок"] >= OUTAGE_SAME_HOUSE].reset_index()

    parts = []
    if len(by_words):
        parts.append("Заявки со словами про отключение или весь дом:\n" + _rows(by_words, now))
    if len(groups):
        parts.append(f"Дома, где {OUTAGE_SAME_HOUSE}+ однотипных заявок:\n" + groups.to_csv(index=False))
    return head + ("\n".join(parts) if parts else "Признаков не найдено.")


def summarize_requests(df: pd.DataFrame, now: datetime) -> str:
    df = prepare_requests(df)
    day_ago = now - timedelta(days=1)
    week_ago = now - timedelta(days=7)
    created = df["_создана"]
    lines = [
        f"Данные с {created.min():%d.%m.%Y} по {created.max():%d.%m.%Y %H:%M}, всего заявок: {len(df)}.",
        f"За последние сутки: создано {(created >= day_ago).sum()}, "
        f"закрыто {(df['_закрыта'] >= day_ago).sum()}.",
        f"За 7 дней: создано {(created >= week_ago).sum()}, закрыто {(df['_закрыта'] >= week_ago).sum()}.",
        "Открытые сейчас по статусам: "
        + ", ".join(f"{k}: {v}" for k, v in df.loc[df["_открыта"], "Статус"].value_counts().items()),
    ]

    # По исполнителям (в одной заявке может быть несколько через запятую).
    ex = (df.assign(Исполнитель=df["Исполнитель"].str.split(r",\s*"))
          .explode("Исполнитель", ignore_index=True))
    ex = ex[ex["Исполнитель"].str.len() > 0]
    hours = (ex["_закрыта"] - ex["_создана"]).dt.total_seconds() / 3600
    age = (now - ex["_создана"]).dt.days
    staff = pd.DataFrame({
        "всего": ex.groupby("Исполнитель").size(),
        "за 7 дней": ex[ex["_создана"] >= week_ago].groupby("Исполнитель").size(),
        "закрыто за сутки": ex[ex["_закрыта"] >= day_ago].groupby("Исполнитель").size(),
        "открыто": ex[ex["_открыта"]].groupby("Исполнитель").size(),
        "открыто дольше 3 дней": ex[ex["_открыта"] & (age > 3)].groupby("Исполнитель").size(),
        "медиана закрытия, ч": hours[~ex["_открыта"]].groupby(ex["Исполнитель"]).median().round(1),
    }).fillna(0).sort_values("всего", ascending=False)
    lines.append("\n### По исполнителям (за весь период выгрузки)\n" + staff.to_csv())

    if "Кем создана" in df.columns:
        who = df[created >= week_ago]["Кем создана"].value_counts()
        lines.append("### Кто принимал заявки за 7 дней\n"
                     + ", ".join(f"{k}: {v}" for k, v in who.items()))

    if "Тип заявки" in df.columns:
        types = pd.DataFrame({
            "за 7 дней": df[created >= week_ago]["Тип заявки"].value_counts(),
            "открыто": df[df["_открыта"]]["Тип заявки"].value_counts(),
        }).fillna(0).astype(int)
        lines.append("### По типам заявок\n" + types.to_csv())

    recent = df[created >= now - timedelta(days=REPEAT_DAYS)]
    houses = recent.groupby("Дом").agg(заявок=("Номер", "size"),
                                       типы=("Тип заявки", lambda s: ", ".join(sorted(set(map(str, s))))),
                                       номера=("Номер", lambda s: ", ".join(map(str, s))))
    houses = houses[houses["заявок"] >= REPEAT_MIN].sort_values("заявок", ascending=False).head(25)
    if len(houses):
        lines.append(f"### Дома с {REPEAT_MIN} и более заявками за {REPEAT_DAYS} дней\n" + houses.to_csv())

    lines.append(outages(df, now))

    detail = df[df["_открыта"] | (created >= day_ago) | (df["_закрыта"] >= day_ago)]
    detail = detail.sort_values("_создана")
    lines.append(f"### Открытые заявки и всё, что изменилось за сутки ({len(detail)} шт.)\n"
                 + _rows(detail, now))
    return "\n\n".join(lines)


TASKS_WINDOW_DAYS = 30  # задачи смотрим поставленные за последний месяц


def _task_flags(df: pd.DataFrame, now: datetime) -> tuple[pd.Series, pd.Series, pd.Series]:
    created = pd.to_datetime(df["Создана"], dayfirst=True, errors="coerce")
    deadline = pd.to_datetime(df["Дедлайн"], dayfirst=True, errors="coerce")
    status = df["Статус"].str.lower()
    review = status == TASK_REVIEW
    overdue = ~status.isin(TASK_DONE) & ~review & (deadline < now)
    return created, review, overdue


def in_period(t: Table, since: datetime, now: datetime | None = None,
              tasks_since: datetime | None = None) -> pd.DataFrame:
    """Только то, что относится к периоду отчёта.
    Заявки: созданы или закрыты с начала периода.
    Задачи: интересны директору только две группы, поставленные с tasks_since
    (по умолчанию — месяц): «Ожидает проверки» и просроченные. В работе, новые
    и т. п. со сроком впереди не нужны."""
    df = t.df
    if is_requests(df):
        p = prepare_requests(df)
        return df[(p["_создана"] >= since) | (p["_закрыта"] >= since)]
    if is_tasks(df):
        now = now or datetime.now()
        tasks_since = tasks_since or now - timedelta(days=TASKS_WINDOW_DAYS)
        created, review, overdue = _task_flags(df, now)
        return df[(created >= tasks_since) & (review | overdue)]
    if is_correspondence(df):
        date = pd.to_datetime(df["Дата документа"], dayfirst=True, errors="coerce")
        return df[date >= since.replace(hour=0, minute=0, second=0, microsecond=0)]
    return df


def tasks_backlog(full: pd.DataFrame, now: datetime, tasks_since: datetime) -> str:
    """Одна строка про старый хвост: такие же задачи, но поставленные раньше окна."""
    created, review, overdue = _task_flags(full, now)
    old = created < tasks_since
    n_review, n_overdue = (old & review).sum(), (old & overdue).sum()
    if not (n_review or n_overdue):
        return ""
    return (f"Поставлены раньше {tasks_since:%d.%m.%Y} и в разбор не включены: ещё "
            f"{n_review} ждут проверки директора и {n_overdue} просрочены — только для "
            "общей картины.\n\n")


def summarize(tables: list[Table], now: datetime, since: datetime | None = None,
              tasks_since: datetime | None = None) -> str:
    blocks = []
    for t in tables:
        backlog = ""
        if since is not None:
            tasks_since = tasks_since or now - timedelta(days=TASKS_WINDOW_DAYS)
            if is_tasks(t.df):
                backlog = tasks_backlog(t.df, now, tasks_since)
            t = Table(t.name, in_period(t, since, now, tasks_since))
        if is_requests(t.df):
            body = summarize_requests(t.df, now)
        elif is_tasks(t.df):
            body = ("Реестр задач, поставленных директором сотрудникам.\n\n" + backlog
                    + summarize_tasks(t.df, now))
        elif is_correspondence(t.df):
            body = "Входящая корреспонденция.\n\n" + summarize_correspondence(t.df, now)
        else:
            body = f"Строк: {len(t.df)}\n\n{t.df.to_csv(index=False)}"
        blocks.append(f"## Файл: {t.name}\n\n{body}")
    return "\n\n".join(blocks)


# ---------- Поиск по полной таблице (для вопросов в боте) ----------

def search(tables: list[Table], query: str, limit: int = 20) -> str:
    """Ищет строки, где встречаются все слова запроса (номер, адрес, фамилия, текст)."""
    words = [w.lower() for w in re.findall(r"\w+", query)]
    if not words:
        return "Пустой запрос."
    now = datetime.now()
    parts = []
    for t in tables:
        df = prepare_requests(t.df) if is_requests(t.df) else t.df
        hay = df.apply(lambda r: " ".join(map(str, r.values)), axis=1).str.lower()
        mask = pd.Series(True, index=df.index)
        for w in words:
            mask &= hay.str.contains(w, regex=False)
        found = df[mask]
        if found.empty:
            continue
        shown = found.tail(limit)
        text = _rows(shown, now) if is_requests(t.df) else shown.to_csv(index=False)
        parts.append(f"## {t.name}: найдено {len(found)}, показано {len(shown)} (самые свежие)\n{text}")
    return "\n\n".join(parts) or "Ничего не найдено. Попробуйте другие слова (например, только фамилию или улицу)."


# ---------- Хранение ----------

def save_tables(tables: list[Table], folder: Path) -> None:
    for t in tables:
        t.df.to_csv(folder / f"table_{t.name}.csv", index=False, encoding="utf-8")


def load_saved(folder: Path) -> list[Table]:
    return [Table(p.stem.removeprefix("table_"), pd.read_csv(p, dtype=str, keep_default_na=False))
            for p in sorted(folder.glob("table_*.csv"))]


def archive(files: list[Path], day: date) -> None:
    target = config.ARCHIVE / day.isoformat()
    target.mkdir(parents=True, exist_ok=True)
    for f in files:
        shutil.move(str(f), target / f.name)
