"""Создаёт демо-выгрузку заявок в data/demo/ (выдуманные данные для проверки)."""
import random
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

random.seed(7)
OUT = Path(__file__).resolve().parent.parent / "data" / "demo" / "demo_заявки.xlsx"

addresses = ["Горьковская 7", "Павловского 3", "Ленина 15", "Садовая 22", "Мира 4"]
kinds = {
    "Сантехника": ["Течь стояка ХВС", "Нет горячей воды", "Засор канализации", "Протечка с потолка"],
    "Электрика": ["Нет света на площадке", "Не работает домофон", "Искрит щиток"],
    "Лифт": ["Лифт застрял", "Лифт не работает"],
    "Уборка": ["Не убран подъезд", "Не вывезен мусор"],
    "Кровля": ["Протекает крыша"],
}
staff = ["Иванов А.", "Петров С.", "Сидорова Е.", "Кузнецов Д."]
names = ["Смирнова О.П.", "Волков И.И.", "Морозова Т.В.", "Лебедев К.А.", "Новикова Н.С."]
now = datetime(2026, 10, 11, 7, 0)

rows = []
for n in range(1, 61):
    kind = random.choice(list(kinds))
    created = now - timedelta(days=random.uniform(0, 10))
    deadline = created + timedelta(days=1 if kind in ("Лифт", "Электрика") else 3)
    status = random.choices(["Выполнена", "В работе", "Новая"], [55, 35, 10])[0]
    closed = created + timedelta(hours=random.uniform(2, 90)) if status == "Выполнена" else None
    rows.append({
        "Номер": 14200 + n,
        "Дата создания": created.strftime("%d.%m.%Y %H:%M"),
        "Адрес": random.choice(addresses),
        "Кв.": random.randint(1, 180),
        "Тип": kind,
        "Описание": random.choice(kinds[kind]),
        "Заявитель": random.choice(names),
        "Телефон": f"+7 9{random.randint(10, 99)} {random.randint(100, 999)}-{random.randint(10, 99)}-{random.randint(10, 99)}",
        "Исполнитель": "Петров С." if kind == "Сантехника" and random.random() < .7 else random.choice(staff),
        "Статус": status,
        "Срок": deadline.strftime("%d.%m.%Y %H:%M"),
        "Дата закрытия": closed.strftime("%d.%m.%Y %H:%M") if closed else "",
    })
# Повторные протечки по одному адресу — «красная точка» для проверки анализа.
for i, d in enumerate([8, 5, 3, 1]):
    rows.append({**rows[0], "Номер": 14300 + i, "Адрес": "Горьковская 7", "Кв.": 178 - i,
                 "Тип": "Кровля", "Описание": "Протекает крыша, звонить 8 912 345-67-89",
                 "Дата создания": (now - timedelta(days=d)).strftime("%d.%m.%Y %H:%M"),
                 "Статус": "В работе", "Дата закрытия": "", "Исполнитель": "Кузнецов Д.",
                 "Срок": (now - timedelta(days=d - 3)).strftime("%d.%m.%Y %H:%M")})

OUT.parent.mkdir(parents=True, exist_ok=True)
pd.DataFrame(rows).to_excel(OUT, index=False)
print(f"Создано: {OUT} ({len(rows)} заявок)")
