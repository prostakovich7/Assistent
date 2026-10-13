"""Телеграм-бот: утренний отчёт по расписанию, отчёт по команде, ответы на вопросы."""
import asyncio
import logging
import re
import socket
import sys
import tempfile
from datetime import datetime, time, timedelta
from pathlib import Path

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import (Application, CommandHandler, ContextTypes, MessageHandler,
                          filters)

from . import analyze, commands, config, report, sources, stt, voice

log = logging.getLogger("assistent")
CHECK_EVERY = 5 * 60  # секунд между проверками «не пора ли отправить отчёт»
INSTANCE_PORT = 47651  # «замок» от второй копии бота
TG_LIMIT = 4000  # Телеграм не принимает сообщения длиннее 4096 знаков


def is_owner(update: Update) -> bool:
    return bool(config.TELEGRAM_CHAT_ID) and str(update.effective_chat.id) == config.TELEGRAM_CHAT_ID


async def send_long(bot, chat_id, text: str) -> None:
    for i in range(0, len(text), TG_LIMIT):
        await bot.send_message(chat_id, text[i:i + TG_LIMIT])


REPORT_LOCK = asyncio.Lock()  # отчёт собирается ~4 минуты — не запускать второй параллельно
MAX_ATTEMPTS = 3              # сколько раз в день пробовать, если сборка падает с ошибкой


async def deliver_report(bot, chat_id, on_demand: bool = False, days: int | None = None) -> str:
    """Собрать и отправить отчёт. Возвращает "ok", "nodata" или "error".
    on_demand — отчёт по запросу: если свежих выгрузок нет, берём последнюю.
    days — период по просьбе директора; иначе — с прошлого отчёта."""
    async with REPORT_LOCK:
        await bot.send_chat_action(chat_id, ChatAction.TYPING)
        fresh = bool(sources.find_files())
        try:
            r = await report.build(allow_previous=on_demand, days=days)
        except report.NoDataError:
            return "nodata"
        except Exception:
            log.exception("Ошибка при сборке отчёта")
            return "error"
        await send_report(bot, chat_id, r)
        # Свежие выгрузки в день планового отчёта — плановый отчёт считаем отправленным.
        if fresh and report.local_now().weekday() in config.REPORT_DAYS:
            report.mark("delivered")
        return "ok"


# «Сделай отчёт», «пришли отчёт», «собери сводку» и т. п. — голосом или текстом.
REPORT_REQUEST_RE = re.compile(
    r"\b(сдела|собер|пришл|подготов|сформир|скин|дай|давай|нуж)\w*\b.{0,25}\b(отч[её]т|сводк)\w*"
    r"|^\s*(отч[её]т|сводк\w*)\W*$", re.I)


# «за месяц», «за две недели», «за 10 дней», «за квартал» → число дней.
PERIOD_RE = re.compile(r"за\s+(?:(\d+|одн\w*|дв\w*|тр\w*|полгода)\s+)?"
                       r"(дн\w*|день|недел\w*|месяц\w*|квартал|полгода)", re.I)
WORD_NUM = {"одн": 1, "дв": 2, "тр": 3}
UNIT_DAYS = {"д": 1, "н": 7, "м": 30, "к": 90, "п": 182}


def requested_days(text: str) -> int | None:
    m = PERIOD_RE.search(text)
    if not m:
        return None
    num, unit = (m.group(1) or "").lower(), m.group(2).lower()
    if num.isdigit():
        n = int(num)
    else:
        n = next((v for k, v in WORD_NUM.items() if num.startswith(k)), 1)
    return n * UNIT_DAYS[unit[0]]


async def report_on_request(update: Update, context: ContextTypes.DEFAULT_TYPE,
                            spoken: bool, text: str = "") -> None:
    say = (lambda t: reply_voice(update, t)) if spoken else update.message.reply_text
    if REPORT_LOCK.locked():
        await say("Отчёт уже собирается, пришлю, как будет готов.")
        return
    days = requested_days(text)
    period = f" за {days} дней" if days else " с прошлого отчёта"
    if sources.find_files():
        await say(f"Собираю отчёт{period} по свежей выгрузке, это займёт минуты четыре.")
    else:
        prev = report.latest()
        when = f" от {prev.exported:%d.%m}" if prev else ""
        await say(f"Новых выгрузок нет, собираю отчёт{period} по последней выгрузке{when}. "
                  "Это займёт минуты четыре.")
    status = await deliver_report(context.bot, update.effective_chat.id, on_demand=True, days=days)
    if status == "nodata":
        await say("Выгрузок из Бурмистра пока не было ни одной, собрать отчёт не из чего.")
    elif status == "error":
        await say("Не получилось собрать отчёт, попробуйте чуть позже.")


async def send_report(bot, chat_id, r: report.Report) -> None:
    caption = f"Отчёт за {r.day.strftime('%d.%m.%Y')}"
    if not r.voice_file.exists():  # при сборке озвучка не удалась — ещё попытка
        try:
            await voice.synthesize(r.voice_text, r.voice_file)
        except Exception:
            log.exception("Озвучка отчёта не удалась, отправляю текстом")
    if r.voice_file.exists():
        # Аудиофайл — несколько сотен килобайт, на загрузку даём до 2 минут.
        with r.voice_file.open("rb") as f:
            await bot.send_voice(chat_id, f, caption=caption, write_timeout=120, read_timeout=60)
    else:
        await bot.send_message(chat_id, f"{caption} (озвучка недоступна)\n\n{r.voice_text}")

    try:
        sent = await asyncio.to_thread(report.send_email, r)
        note = "Полный отчёт отправлен на почту." if sent else \
               "Почта пока не настроена, поэтому полный отчёт присылаю сюда."
    except Exception:
        log.exception("Ошибка отправки почты")
        sent, note = False, "Не удалось отправить отчёт на почту, присылаю полный отчёт сюда."
    await bot.send_message(chat_id, note + " Можете задать мне любой вопрос по отчёту.")
    if not sent:
        await send_long(bot, chat_id, r.full)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if not config.TELEGRAM_CHAT_ID:
        await update.message.reply_text(
            f"Здравствуйте! Ваш номер чата: {chat_id}\n"
            "Впишите его в файл .env в строку TELEGRAM_CHAT_ID и перезапустите агента.")
        return
    if not is_owner(update):
        return
    days = ", ".join(DAY_NAMES[d] for d in sorted(config.REPORT_DAYS))
    await update.message.reply_text(
        f"Здравствуйте! Автоматический отчёт — {days} после {config.REPORT_TIME}.\n"
        "Отчёт по запросу: /report или голосом «сделай отчёт».\n"
        "Вопросы можно задавать голосом или текстом, например: «что с заявками по Горьковской?»")


DAY_NAMES = ("понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье")


async def report_now(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if is_owner(update):  # «/report за месяц» тоже работает
        await report_on_request(update, context, spoken=False, text=update.message.text or "")


HISTORY_TURNS = 6  # сколько последних вопросов-ответов помнить для уточнений


def history(context: ContextTypes.DEFAULT_TYPE, r: report.Report) -> list[tuple[str, str]]:
    """История разговора по текущему отчёту; с новым отчётом начинается заново."""
    data = context.chat_data
    if data.get("report_day") != r.day:
        data["report_day"], data["history"] = r.day, []
    return data["history"]


async def reply_voice(update: Update, text: str, caption: str = "") -> None:
    with tempfile.TemporaryDirectory() as tmp:
        try:
            path = await voice.synthesize(text, Path(tmp) / "answer.mp3")
        except Exception:
            # Сервис озвучки не ответил — лучше текст, чем тишина.
            log.exception("Озвучка не удалась, отвечаю текстом")
            await update.message.reply_text(f"{caption}\n\n{text}".strip())
            return
        with path.open("rb") as f:
            await update.message.reply_voice(f, caption=caption[:1000] or None,
                                             write_timeout=120, read_timeout=60)


async def answer_question(update: Update, context: ContextTypes.DEFAULT_TYPE,
                          text: str, spoken: bool) -> None:
    if REPORT_REQUEST_RE.search(text):
        await report_on_request(update, context, spoken, text)
        return
    pending = context.chat_data.get("pending_tasks")
    if pending or commands.COMMAND_RE.search(text):
        if await handle_command(update, context, text, spoken, pending):
            return
    r = report.latest()
    if r is None:
        msg = "Отчётов пока нет. Пришлите /report, чтобы собрать первый."
        await (reply_voice(update, msg) if spoken else update.message.reply_text(msg))
        return
    turns = history(context, r)
    await update.effective_chat.send_action(
        ChatAction.RECORD_VOICE if spoken else ChatAction.TYPING)
    try:
        reply = await asyncio.to_thread(analyze.answer, text, r.full, r.data, r.tables(),
                                        list(turns), spoken)
        turns.append((text, reply))
        del turns[:-HISTORY_TURNS]
    except Exception:
        log.exception("Ошибка при ответе на вопрос")
        reply = "Не получилось ответить, попробуйте ещё раз чуть позже."
    if spoken:
        await reply_voice(update, reply, caption=f"Вопрос: {text}")
    else:
        await send_long(context.bot, update.effective_chat.id, reply)


async def handle_command(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str,
                         spoken: bool, pending: list | None) -> bool:
    """Поручение сотрудникам: разобрать → зачитать → после «да» в очередь.
    Возвращает False, если это оказалось не поручение (тогда ответим как на вопрос)."""
    say = (lambda t: reply_voice(update, t, caption=f"Вы: {text}")) if spoken \
        else update.message.reply_text
    await update.effective_chat.send_action(
        ChatAction.RECORD_VOICE if spoken else ChatAction.TYPING)
    try:
        result = await asyncio.to_thread(commands.parse, text, pending)
    except Exception:
        log.exception("Ошибка разбора поручения")
        await say("Не получилось разобрать поручение, повторите, пожалуйста.")
        return True
    log.info("Поручение: %s → %s", text, result)
    intent = result["intent"]
    if intent == "tasks" and result["tasks"]:
        context.chat_data["pending_tasks"] = result["tasks"]
        msg = commands.confirmation(result["tasks"])
        if result["question"]:
            msg = msg.replace(" Подтверждаете?", f" {result['question']}")
        await say(msg)
    elif intent == "tasks":
        await say(result["question"] or "Не понял, кому и что поручить. Повторите, пожалуйста.")
    elif intent == "confirm" and pending:
        commands.enqueue(pending, text)
        context.chat_data.pop("pending_tasks", None)
        n = len(pending)
        await say(("Принято, задача поставлена" if n == 1 else f"Принято, {n} задачи поставлены")
                  + " в очередь на создание в Бурмистре.")
    elif intent == "cancel" and pending:
        context.chat_data.pop("pending_tasks", None)
        await say("Хорошо, отменил.")
    else:
        return False  # вопрос или что-то другое — отвечаем как обычно
    return True


async def question(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if is_owner(update):
        await answer_question(update, context, update.message.text, spoken=False)


async def voice_question(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Голосовой вопрос → распознать → ответить коротким голосовым."""
    if not is_owner(update):
        return
    await update.effective_chat.send_action(ChatAction.RECORD_VOICE)
    media = update.message.voice or update.message.audio
    try:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "question.ogg"
            await (await media.get_file()).download_to_drive(path)
            text = await asyncio.to_thread(stt.transcribe, path)
    except Exception:
        log.exception("Ошибка распознавания голоса")
        await reply_voice(update, "Не получилось разобрать голосовое, повторите, пожалуйста.")
        return
    log.info("Голосовой вопрос: %s", text)
    if not text:
        await reply_voice(update, "Не расслышал вопрос, повторите, пожалуйста.")
        return
    await answer_question(update, context, text, spoken=True)


async def report_check(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Раз в несколько минут: время отчёта прошло, а сегодня он не отправлен — отправить.
    Так отчёт придёт и тогда, когда компьютер включили или разбудили позже 8:00."""
    hh, mm = map(int, config.REPORT_TIME.split(":"))
    now = report.local_now()
    start = datetime.combine(now.date(), time(hh, mm))
    if now.weekday() not in config.REPORT_DAYS or now < start:
        return
    if report.done_today("delivered") or REPORT_LOCK.locked():
        return
    if report.attempts_today() >= MAX_ATTEMPTS:
        return
    chat_id = int(config.TELEGRAM_CHAT_ID)
    if not sources.find_files():
        # Автовыгрузка через Chrome идёт несколько минут — сразу не тревожим.
        grace_over = now >= start + timedelta(minutes=config.NODATA_GRACE_MIN)
        if grace_over and not report.done_today("nodata_notified"):
            report.mark("nodata_notified")
            msg = ("Доброе утро. Свежих выгрузок из Бурмистра пока нет, отчёт пришлю, "
                   "как только они появятся.")
            with tempfile.TemporaryDirectory() as tmp:
                path = await voice.synthesize(msg, Path(tmp) / "nodata.mp3")
                with path.open("rb") as f:
                    await context.bot.send_voice(chat_id, f, write_timeout=120, read_timeout=60)
        return
    report.add_attempt()
    status = await deliver_report(context.bot, chat_id)
    if status == "error" and report.attempts_today() >= MAX_ATTEMPTS:
        await context.bot.send_message(chat_id, "Сегодня не получилось собрать отчёт за "
                                                f"{MAX_ATTEMPTS} попытки, подробности в agent.log.")


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    log.error("Необработанная ошибка", exc_info=context.error)


def single_instance() -> socket.socket:
    """Не даём запустить вторую копию бота: Телеграм не позволяет двум копиям
    получать сообщения одновременно. Занятый порт = бот уже работает."""
    lock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        lock.bind(("127.0.0.1", INSTANCE_PORT))
    except OSError:
        log.info("Бот уже запущен, вторая копия не нужна")
        raise SystemExit(0)
    return lock


def main() -> None:
    handlers = [logging.FileHandler(config.ROOT / "agent.log", encoding="utf-8")]
    if sys.stderr is not None:  # при запуске без окна (pythonw) консоли нет
        handlers.append(logging.StreamHandler())
    logging.basicConfig(level=logging.INFO, handlers=handlers,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    if not config.TELEGRAM_BOT_TOKEN:
        raise SystemExit("Не задан TELEGRAM_BOT_TOKEN в файле .env")
    _lock = single_instance()  # noqa: F841 — держим порт до выхода

    # Связь с Телеграмом бывает медленной — увеличенные таймауты вместо 5 секунд по умолчанию.
    app = (Application.builder().token(config.TELEGRAM_BOT_TOKEN)
           .connect_timeout(30).read_timeout(30).write_timeout(60).pool_timeout(30)
           .build())
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("report", report_now))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, question))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, voice_question))
    app.add_error_handler(on_error)

    if config.TELEGRAM_CHAT_ID:
        # Проверка каждые 5 минут, первая — через 30 секунд после запуска.
        app.job_queue.run_repeating(report_check, interval=CHECK_EVERY, first=30)
        log.info("Ежедневный отчёт с %s (%s), проверка каждые %d мин",
                 config.REPORT_TIME, config.TIMEZONE, CHECK_EVERY // 60)

    log.info("Бот запущен")
    # После включения компьютера интернет появляется не сразу — ждём, а не падаем.
    app.run_polling(bootstrap_retries=-1)


if __name__ == "__main__":
    main()
