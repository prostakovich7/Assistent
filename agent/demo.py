"""Пример отчёта на мок-данных, без Telegram и без нейросети.

    python -m agent.demo               — собрать отчёт, сохранить в reports/пример/
    python -m agent.demo Соколов       — подробности по сотруднику, отделу, дому или задаче
"""
import asyncio
import sys

from . import company, config, digest, voice

MOCK = config.ROOT / "data" / "mock" / "company.json"
OUT = config.REPORTS / "пример"


def main() -> None:
    c = company.load(MOCK)
    if len(sys.argv) > 1:
        print(digest.details(c, " ".join(sys.argv[1:])))
        return

    d = digest.build(c)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "короткий.txt").write_text(d.short, encoding="utf-8")
    (OUT / "полный.md").write_text(d.full, encoding="utf-8")
    print(d.short)
    print(f"\nСохранено: {OUT / 'короткий.txt'}\n           {OUT / 'полный.md'}")

    try:  # озвучка — по желанию, нужен интернет
        asyncio.run(voice.synthesize(d.short, OUT / "короткий.mp3"))
        print(f"           {OUT / 'короткий.mp3'}")
    except Exception as e:
        print(f"Озвучка не получилась ({e.__class__.__name__}), текстовый отчёт готов.")


if __name__ == "__main__":
    main()
