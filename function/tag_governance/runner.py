"""ประกอบทุกอย่าง: อ่านค่า config -> ดึงข้อมูล -> คำนวณ -> (ส่งเมล + บันทึก state)"""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from . import core, schedule
from .queries import filter_scope

TZ = timezone(timedelta(hours=7))  # เวลาไทย (UTC+7 ไม่มี DST) ไม่ใช้ zoneinfo เพราะบางเครื่องไม่มีฐานข้อมูลเขตเวลา ทำให้ import ล้ม
HOLIDAYS_FILE = Path(__file__).resolve().parent.parent / "holidays.json"


def _split(v: str) -> list[str]:
    return [x.strip() for x in (v or "").replace(";", ",").split(",") if x.strip()]


def http_enabled() -> bool:
    """endpoint /api/run ปิดเป็นค่าเริ่มต้น (เปิดเฉพาะตอนทดสอบด้วย TG_HTTP_ENABLED=true)"""
    return os.environ.get("TG_HTTP_ENABLED", "false").strip().lower() in ("true", "1", "yes")


def manual_send_enabled() -> bool:
    """endpoint /api/send (ส่งเมลทันทีตอนไหนก็ได้) ปิดเป็นค่าเริ่มต้น เปิดด้วย TG_MANUAL_SEND_ENABLED=true"""
    return os.environ.get("TG_MANUAL_SEND_ENABLED", "false").strip().lower() in ("true", "1", "yes")


def today_th() -> date:
    return datetime.now(TZ).date()


def run(
    today: date | None = None, dry_run: bool = True, force: bool = False, items: list[dict] | None = None, store=None, persist: bool = True
) -> dict:
    """dry_run=True: ไม่ส่งเมล ไม่บันทึก state (แค่แสดงว่าจะส่งอะไร)
    force=True: ข้ามการเช็กว่าวันนี้เป็นวันส่งหรือไม่ (ใช้ตอนทดสอบ)
    persist=False: ส่งเมลได้ แต่ไม่บันทึก state/snapshot (ใช้กับการส่งนอกรอบ ไม่ให้กระทบรอบ escalation รายสัปดาห์)"""
    today = today or today_th()
    holidays = schedule.load_holidays(HOLIDAYS_FILE)
    if not force and not schedule.is_send_day(today, holidays):
        return {"status": "skipped", "reason": "ไม่ใช่วันส่ง (ไม่ใช่วันทำงานแรกของสัปดาห์)", "today": today.isoformat()}

    sla = int(os.environ.get("TG_SLA_DAYS", core.SLA_DAYS_DEFAULT))
    if items is None:
        from azure.identity import DefaultAzureCredential

        from .queries import fetch_items

        items = fetch_items(DefaultAzureCredential(), os.environ.get("TG_ASSIGNMENT_NAME", "rg-tag-governance-audit"), _split(os.environ.get("TG_SUBSCRIPTION_IDS", "")))
    items = filter_scope(items, os.environ.get("TG_RG_NAME_REGEX", ""))
    if store is None:
        from .store import BlobStore

        store = BlobStore(os.environ["AzureWebJobsStorage"])

    state = store.get("state.json") or core.empty_state()
    email, new_state, summary = core.run_report(items, state, today, sla, os.environ.get("TG_WORKBOOK_URL", ""))
    mail_enabled = os.environ.get("TG_MAIL_ENABLED", "true").strip().lower() not in ("false", "0", "no")
    result = {"status": "ok", "today": today.isoformat(), "summary": summary, "dry_run": dry_run, "mail_enabled": mail_enabled, "persist": persist}

    if email is None:
        result["email"] = "ไม่ส่ง (ทุกรายการผ่านแล้ว)"
    else:
        to = _split(os.environ.get("TG_MAIL_TO", ""))
        cc = _split(os.environ.get("TG_MAIL_CC", ""))
        if email["cc_managers"]:
            cc += [c for c in _split(os.environ.get("TG_MAIL_CC_ESCALATION", "")) if c.lower() not in {x.lower() for x in cc}]
        result["email"] = {"to": to, "cc": cc, "subject": email["subject"]}
        if dry_run:
            result["email"]["text_preview"] = email["text"]
        elif not mail_enabled:
            # ช่วงเก็บ snapshot ก่อนเริ่มส่งเมล: ไม่ส่ง และไม่บันทึกว่า "ยกระดับแล้ว" (กันขั้น 2 เกิดโดยที่ยังไม่เคยแจ้ง)
            new_state = core.update_state(items, state, today)[0]
            result["email"]["sent"] = False
        else:
            from .mailer import send_email

            result["email"]["message_id"] = send_email(
                os.environ["TG_ACS_CONNECTION_STRING"], os.environ["TG_MAIL_SENDER"], to, cc, email["subject"], email["html"], email["text"]
            )

    if not dry_run and persist:
        store.put("state.json", new_state)
        store.put(f"snapshots/{today.isoformat()}.json", {"date": today.isoformat(), "items": items, "summary": summary})
    return result
