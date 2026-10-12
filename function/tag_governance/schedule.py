"""ตัดสินว่าวันนี้ควรส่งรายงานไหม: ส่งวันทำงานแรกของสัปดาห์ (ปกติคือวันจันทร์,
ถ้าจันทร์เป็นวันหยุดจะเลื่อนเป็นวันถัดไป)"""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path


def load_holidays(path: str | Path) -> set[date]:
    p = Path(path)
    if not p.exists():
        return set()
    data = json.loads(p.read_text(encoding="utf-8"))
    return {date.fromisoformat(d) for d in data.get("dates", [])}


def is_working_day(d: date, holidays: set[date]) -> bool:
    return d.weekday() < 5 and d not in holidays


def is_send_day(today: date, holidays: set[date]) -> bool:
    """True ถ้า today คือวันทำงานแรกของสัปดาห์ (จันทร์-ศุกร์) นั้น"""
    if not is_working_day(today, holidays):
        return False
    monday = today - timedelta(days=today.weekday())
    d = monday
    while d < today:
        if is_working_day(d, holidays):
            return False
        d += timedelta(days=1)
    return True
