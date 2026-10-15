"""Сборка ежедневного отчёта: данные → анализ → голос → файлы в reports/<дата>/."""
import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from . import analyze, config, db, mailer, sources, voice


@dataclass
class Report:
    day: date
    folder: Path

    @property
    def data(self) -> str:
        return (self.folder / "data.md").read_text(encoding="utf-8")

    @property
    def full(self) -> str:
        return (self.folder / "report.md").read_text(encoding="utf-8")

    @property
    def voice_text(self) -> str:
        return (self.folder / "voice.txt").read_text(encoding="utf-8")

    @property
    def voice_file(self) -> Path:
        return self.folder / "voice.mp3"

    def tables(self) -> list[sources.Table]:
        return sources.load_saved(self.folder)

    @property
    def exported(self) -> datetime:
        """Когда выгружены данные, по которым собран отчёт."""
        try:
            meta = json.loads((self.folder / "meta.json").read_text(encoding="utf-8"))
            return datetime.fromisoformat(meta["exported"])
        except (FileNotFoundError, KeyError, ValueError):
            return datetime.combine(self.day, datetime.min.time())


class NoDataError(Exception):
    pass


def local_now() -> datetime:
    """Текущее время по часовому поясу компании (в нём же даты в выгрузках)."""
    return datetime.now(ZoneInfo(config.TIMEZONE)).replace(tzinfo=None)


DEFAULT_PERIOD_DAYS = 7  # первый отчёт — за неделю


def period_start(exported: datetime, days: int | None = None) -> datetime:
    """Начало периода отчёта: явно заданное число дней, иначе — с конца прошлого отчёта,
    а если его не было (или он старше месяца) — неделя назад."""
    if days:
        return exported - timedelta(days=days)
    last = db.get_state("last_period_end")
    if last:
        start = datetime.fromisoformat(last)
        if exported - timedelta(days=31) < start < exported:
            return start
    return exported - timedelta(days=DEFAULT_PERIOD_DAYS)


async def build(allow_previous: bool = False, days: int | None = None) -> Report:
    """Собрать отчёт по свежим выгрузкам из data/inbox. allow_previous — если свежих нет,
    взять данные последней выгрузки (для отчёта по запросу между плановыми днями).
    days — глубина периода по просьбе директора («за месяц»), иначе — с прошлого отчёта."""
    now = local_now()
    day = now.date()
    tables, files = sources.load()
    if files:
        exported = datetime.fromtimestamp(max(f.stat().st_mtime for f in files))
    else:
        prev = latest() if allow_previous else None
        if prev is None or not prev.tables():
            raise NoDataError(f"В папке {config.INBOX} нет выгрузок из Бурмистра.")
        tables, exported = prev.tables(), prev.exported
    # «За сутки», «дней с создания» и т. п. считаем от момента выгрузки, а не от «сейчас».
    since = period_start(exported, days)
    # Задачи — за месяц (или глубже, если директор попросил период длиннее).
    tasks_since = exported - timedelta(days=max(days or 0, sources.TASKS_WINDOW_DAYS))
    data = (f"Дата выгрузки данных из CRM: {exported:%d.%m.%Y %H:%M}.\n"
            f"Период отчёта: с {since:%d.%m.%Y %H:%M} по {exported:%d.%m.%Y %H:%M} — "
            "заявки, созданные или закрытые за период, и входящие письма за период. "
            f"Задачи — поставленные с {tasks_since:%d.%m.%Y}, только «Ожидает проверки» "
            "и просроченные.\n\n"
            + sources.summarize(tables, exported, since, tasks_since))

    voice_text, full = await asyncio.to_thread(analyze.make_report, data, now)

    folder = config.REPORTS / day.isoformat()
    folder.mkdir(parents=True, exist_ok=True)
    sources.save_tables(tables, folder)
    (folder / "meta.json").write_text(json.dumps({"exported": exported.isoformat(),
                                                  "since": since.isoformat()}),
                                      encoding="utf-8")
    db.set_state("last_period_end", exported.isoformat())  # следующий отчёт начнётся отсюда
    db.log_report(day.isoformat(), exported.isoformat(), since.isoformat(), str(folder), voice_text)
    (folder / "data.md").write_text(data, encoding="utf-8")
    (folder / "report.md").write_text(full, encoding="utf-8")
    (folder / "voice.txt").write_text(voice_text, encoding="utf-8")
    report = Report(day, folder)
    report.voice_file.unlink(missing_ok=True)  # старая озвучка от прошлой сборки за этот день
    try:
        await voice.synthesize(voice_text, report.voice_file)
    except Exception:
        # Анализ уже оплачен и сохранён — не теряем отчёт из-за сбоя озвучки.
        logging.getLogger("assistent").exception("Озвучка отчёта не удалась")

    sources.archive(files, day)
    return report


def send_email(report: Report) -> bool:
    """Отправляет полный отчёт на почту. False — если почта ещё не настроена."""
    if not mailer.is_configured():
        return False
    mailer.send_report(
        subject=f"Отчёт {config.COMPANY_NAME} за {report.day.strftime('%d.%m.%Y')}",
        report_md=report.full,
        attachments=[report.folder / "report.md"],
    )
    return True


# ---------- Что уже сделано сегодня (в базе — переживает перезапуск и выключение) ----------

def _today() -> str:
    return local_now().date().isoformat()


def mark(key: str) -> None:
    """Отметить событие сегодняшним днём: delivered — отчёт отправлен, nodata_notified —
    предупредили, что выгрузок нет."""
    db.set_state(key, _today())


def done_today(key: str) -> bool:
    return db.get_state(key) == _today()


def attempts_today() -> int:
    if db.get_state("attempts_day") != _today():
        return 0
    return int(db.get_state("attempts", "0"))


def add_attempt() -> None:
    db.set_state("attempts", str(attempts_today() + 1))
    db.set_state("attempts_day", _today())


def latest() -> Report | None:
    # Только папки-даты вида 2026-10-11 (папка «пример» — для демо-отчёта).
    folders = sorted(p for p in config.REPORTS.glob("????-??-??") if p.is_dir())
    if not folders:
        return None
    folder = folders[-1]
    return Report(date.fromisoformat(folder.name), folder)
