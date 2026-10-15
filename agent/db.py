"""Локальная база SQLite (data/assistent.db): всё, что должно пережить перезапуск бота.

- state    — служебные отметки: отправлен ли сегодня отчёт, конец прошлого периода и т. п.
- reports  — журнал собранных отчётов
- dialog   — история вопросов и ответов в боте (для уточнений «а по Ивановой?»)
- pending  — зачитанные, но ещё не подтверждённые поручения
- tasks    — подтверждённые поручения (очередь на создание в CRM)
- costs    — расходы на Claude по каждому запросу
"""
import csv
import json
import sqlite3
from contextlib import closing
from datetime import datetime

from . import config

DB = config.ROOT / "data" / "assistent.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS state   (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS reports (day TEXT PRIMARY KEY, exported TEXT, since TEXT,
                                    folder TEXT, voice_text TEXT, created TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS dialog  (id INTEGER PRIMARY KEY, chat_id INTEGER NOT NULL,
                                    report_day TEXT, question TEXT NOT NULL,
                                    answer TEXT NOT NULL, created TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS pending (chat_id INTEGER PRIMARY KEY, tasks TEXT NOT NULL,
                                    updated TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS tasks   (id INTEGER PRIMARY KEY, created TEXT NOT NULL,
                                    assignee TEXT, text TEXT, deadline TEXT,
                                    letter_number TEXT, letter_id TEXT,
                                    status TEXT NOT NULL DEFAULT 'new', source TEXT, result TEXT);
CREATE TABLE IF NOT EXISTS costs   (id INTEGER PRIMARY KEY, created TEXT NOT NULL, kind TEXT,
                                    input INTEGER, output INTEGER, cache_read INTEGER,
                                    cache_write INTEGER, usd REAL);
"""


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def _query(sql: str, args: tuple = ()) -> list[sqlite3.Row]:
    with closing(connect()) as conn, conn:
        return conn.execute(sql, args).fetchall()


def _execute(sql: str, args: tuple = ()) -> int:
    with closing(connect()) as conn, conn:
        return conn.execute(sql, args).lastrowid


# ---------- Служебные отметки ----------

def get_state(key: str, default: str | None = None) -> str | None:
    rows = _query("SELECT value FROM state WHERE key = ?", (key,))
    return rows[0]["value"] if rows else default


def set_state(key: str, value: str) -> None:
    _execute("INSERT INTO state (key, value) VALUES (?, ?) "
             "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))


# ---------- Отчёты ----------

def log_report(day: str, exported: str, since: str, folder: str, voice_text: str) -> None:
    _execute("INSERT INTO reports (day, exported, since, folder, voice_text, created) "
             "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(day) DO UPDATE SET exported = excluded.exported, "
             "since = excluded.since, folder = excluded.folder, voice_text = excluded.voice_text, "
             "created = excluded.created", (day, exported, since, folder, voice_text, _now()))


# ---------- Разговор в боте ----------

def add_dialog(chat_id: int, report_day: str, question: str, answer: str) -> None:
    _execute("INSERT INTO dialog (chat_id, report_day, question, answer, created) "
             "VALUES (?, ?, ?, ?, ?)", (chat_id, report_day, question, answer, _now()))


def get_dialog(chat_id: int, report_day: str, limit: int) -> list[tuple[str, str]]:
    """Последние вопросы-ответы по текущему отчёту, от старых к новым."""
    rows = _query("SELECT question, answer FROM dialog WHERE chat_id = ? AND report_day = ? "
                  "ORDER BY id DESC LIMIT ?", (chat_id, report_day, limit))
    return [(r["question"], r["answer"]) for r in reversed(rows)]


# ---------- Поручения ----------

def get_pending(chat_id: int) -> list[dict] | None:
    rows = _query("SELECT tasks FROM pending WHERE chat_id = ?", (chat_id,))
    return json.loads(rows[0]["tasks"]) if rows else None


def set_pending(chat_id: int, tasks: list[dict]) -> None:
    _execute("INSERT INTO pending (chat_id, tasks, updated) VALUES (?, ?, ?) "
             "ON CONFLICT(chat_id) DO UPDATE SET tasks = excluded.tasks, updated = excluded.updated",
             (chat_id, json.dumps(tasks, ensure_ascii=False), _now()))


def clear_pending(chat_id: int) -> None:
    _execute("DELETE FROM pending WHERE chat_id = ?", (chat_id,))


def add_task(task: dict, source: str, created: str | None = None, status: str = "new") -> int:
    return _execute(
        "INSERT INTO tasks (created, assignee, text, deadline, letter_number, letter_id, status, "
        "source) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (created or _now(), task.get("assignee", ""), task.get("text", ""),
         task.get("deadline", ""), task.get("letter_number", ""), task.get("letter_id", ""),
         status, source))


# ---------- Расходы ----------

def add_cost(kind: str, tok: dict, usd: float, created: str | None = None) -> None:
    _execute("INSERT INTO costs (created, kind, input, output, cache_read, cache_write, usd) "
             "VALUES (?, ?, ?, ?, ?, ?, ?)",
             (created or _now(), kind, tok["input"], tok["output"], tok["cache_read"],
              tok["cache_write"], usd))


# ---------- Сводка (команда /база в боте) ----------

def summary(chat_id: int | None = None) -> str:
    def one(sql, args=()):
        return _query(sql, args)[0][0]
    last = _query("SELECT day, exported, created FROM reports ORDER BY day DESC LIMIT 1")
    lines = [f"База: {DB.name}, {DB.stat().st_size // 1024} КБ" if DB.exists() else "База пуста"]
    if last:
        r = last[0]
        lines.append(f"Последний отчёт: за {r['day']} (данные от {r['exported'][:16].replace('T', ' ')})")
    lines.append(f"Отчётов в журнале: {one('SELECT COUNT(*) FROM reports')}")
    lines.append("Отчёт отправлен: " + (get_state("delivered") or "—")
                 + ", конец прошлого периода: " + (get_state("last_period_end") or "—")[:16].replace("T", " "))
    lines.append(f"Вопросов в истории: {one('SELECT COUNT(*) FROM dialog')}")
    for r in _query("SELECT created, question FROM dialog ORDER BY id DESC LIMIT 3"):
        lines.append(f"  • {r['created'][5:16].replace('T', ' ')} — {r['question'][:60]}")
    if chat_id is not None and get_pending(chat_id):
        lines.append(f"Ждут вашего «да»: {len(get_pending(chat_id))} поручение(я)")
    lines.append(f"Поручений в очереди: {one('SELECT COUNT(*) FROM tasks')}")
    for r in _query("SELECT id, assignee, text, status FROM tasks ORDER BY id DESC LIMIT 3"):
        lines.append(f"  • №{r['id']} {r['assignee'].split(' ')[0]}: {r['text'][:50]} [{r['status']}]")
    usd = one("SELECT COALESCE(SUM(usd), 0) FROM costs")
    lines.append(f"Расходы на Claude: ${usd:.2f} за {one('SELECT COUNT(*) FROM costs')} запросов")
    return "\n".join(lines)


# ---------- Разовый перенос старых файлов в базу ----------

def migrate_files() -> None:
    """state.json, очередь data/queue/*.json и costs.csv → база (один раз)."""
    if get_state("migrated_files"):
        return
    data = config.ROOT / "data"
    state_file = data / "state.json"
    if state_file.exists():
        try:
            for k, v in json.loads(state_file.read_text(encoding="utf-8")).items():
                set_state(k, str(v))
        except json.JSONDecodeError:
            pass
    for f in sorted((data / "queue").glob("*.json")) if (data / "queue").exists() else []:
        if f.name.endswith(".result.json"):
            continue
        item = json.loads(f.read_text(encoding="utf-8"))
        add_task(item, item.get("source", ""), item.get("created"), item.get("status", "new"))
    costs = data / "costs.csv"
    if costs.exists():
        with costs.open(encoding="utf-8") as fh:
            for row in csv.DictReader(fh, delimiter=";"):
                tok = {"input": int(row["вход"]), "output": int(row["выход"]),
                       "cache_read": int(row["кэш_чтение"]), "cache_write": int(row["кэш_запись"])}
                add_cost(row["вид"], tok, float(row["usd"]), row["время"].replace(" ", "T"))
    for folder in sorted(config.REPORTS.glob("????-??-??")) if config.REPORTS.exists() else []:
        meta, voice = folder / "meta.json", folder / "voice.txt"
        m = json.loads(meta.read_text(encoding="utf-8")) if meta.exists() else {}
        log_report(folder.name, m.get("exported", ""), m.get("since", ""), str(folder),
                   voice.read_text(encoding="utf-8") if voice.exists() else "")
    set_state("migrated_files", _now())
