"""Настройки из файла .env."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

INBOX = ROOT / "data" / "inbox"      # сюда кладутся выгрузки из Бурмистра
ARCHIVE = ROOT / "data" / "archive"  # обработанные выгрузки
REPORTS = ROOT / "reports"           # готовые отчёты по дням

MODEL = "claude-opus-5-5"


def env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


COMPANY_NAME = env("COMPANY_NAME", "Управляющая компания")
TELEGRAM_BOT_TOKEN = env("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = env("TELEGRAM_CHAT_ID")
SMTP_HOST = env("SMTP_HOST")
SMTP_PORT = int(env("SMTP_PORT", "465") or 465)
SMTP_USER = env("SMTP_USER")
SMTP_PASSWORD = env("SMTP_PASSWORD")
REPORT_EMAIL_TO = env("REPORT_EMAIL_TO")
REPORT_TIME = env("REPORT_TIME", "08:00")
# Дни автоматического отчёта: 0 — понедельник … 6 — воскресенье. По умолчанию пн и пт.
REPORT_DAYS = {int(d) for d in env("REPORT_DAYS", "0,4").split(",") if d.strip()}
# Сколько минут после REPORT_TIME ждать выгрузку, прежде чем сказать «выгрузок нет»
# (автовыгрузка через Chrome занимает несколько минут).
NODATA_GRACE_MIN = int(env("NODATA_GRACE_MIN", "60") or 60)
TIMEZONE = env("TIMEZONE", "Asia/Novokuznetsk")
VOICE = env("VOICE", "ru-RU-DmitryNeural")
# Скорость речи и длина голосовой сводки: ~15 знаков в секунду, 800 знаков ≈ 1 минута.
VOICE_RATE = env("VOICE_RATE", "+10%")
VOICE_MAX_CHARS = int(env("VOICE_MAX_CHARS", "800") or 800)
# Голосовой ответ на вопрос — короче: ~400 знаков ≈ 25 секунд.
ANSWER_VOICE_MAX_CHARS = int(env("ANSWER_VOICE_MAX_CHARS", "400") or 400)
# Модель распознавания речи: small — баланс скорости и качества (tiny/base быстрее, medium точнее).
WHISPER_MODEL = env("WHISPER_MODEL", "small")
