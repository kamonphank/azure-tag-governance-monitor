"""เธเธฃเธฐเธเธญเธเธ—เธธเธเธญเธขเนเธฒเธ: เธญเนเธฒเธเธเนเธฒ config -> เธ”เธถเธเธเนเธญเธกเธนเธฅ -> เธเธณเธเธงเธ“ -> (เธชเนเธเน€เธกเธฅ + เธเธฑเธเธ—เธถเธ state)"""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from . import core, schedule
from .queries import filter_scope

TZ = timezone(timedelta(hours=7))  # เน€เธงเธฅเธฒเนเธ—เธข (UTC+7 เนเธกเนเธกเธต DST) เนเธกเนเนเธเน zoneinfo เน€เธเธฃเธฒเธฐเธเธฒเธเน€เธเธฃเธทเนเธญเธเนเธกเนเธกเธตเธเธฒเธเธเนเธญเธกเธนเธฅเน€เธเธ•เน€เธงเธฅเธฒ เธ—เธณเนเธซเน import เธฅเนเธก
HOLIDAYS_FILE = Path(__file__).resolve().parent.parent / "holidays.json"


def _split(v: str) -> list[str]:
    return [x.strip() for x in (v or "").replace(";", ",").split(",") if x.strip()]


def http_enabled() -> bool:
    """endpoint /api/run เธเธดเธ”เน€เธเนเธเธเนเธฒเน€เธฃเธดเนเธกเธ•เนเธ (เน€เธเธดเธ”เน€เธเธเธฒเธฐเธ•เธญเธเธ—เธ”เธชเธญเธเธ”เนเธงเธข TG_HTTP_ENABLED=true)"""
    return os.environ.get("TG_HTTP_ENABLED", "false").strip().lower() in ("true", "1", "yes")


def manual_send_enabled() -> bool:
    """endpoint /api/send (เธชเนเธเน€เธกเธฅเธ—เธฑเธเธ—เธตเธ•เธญเธเนเธซเธเธเนเนเธ”เน) เธเธดเธ”เน€เธเนเธเธเนเธฒเน€เธฃเธดเนเธกเธ•เนเธ เน€เธเธดเธ”เธ”เนเธงเธข TG_MANUAL_SEND_ENABLED=true"""
    return os.environ.get("TG_MANUAL_SEND_ENABLED", "false").strip().lower() in ("true", "1", "yes")


def today_th() -> date:
    return datetime.now(TZ).date()


def run(
    today: date | None = None, dry_run: bool = True, force: bool = False, items: list[dict] | None = None, store=None, persist: bool = True
) -> dict:
    """dry_run=True: เนเธกเนเธชเนเธเน€เธกเธฅ เนเธกเนเธเธฑเธเธ—เธถเธ state (เนเธเนเนเธชเธ”เธเธงเนเธฒเธเธฐเธชเนเธเธญเธฐเนเธฃ)
    force=True: เธเนเธฒเธกเธเธฒเธฃเน€เธเนเธเธงเนเธฒเธงเธฑเธเธเธตเนเน€เธเนเธเธงเธฑเธเธชเนเธเธซเธฃเธทเธญเนเธกเน (เนเธเนเธ•เธญเธเธ—เธ”เธชเธญเธ)
    persist=False: เธชเนเธเน€เธกเธฅเนเธ”เน เนเธ•เนเนเธกเนเธเธฑเธเธ—เธถเธ state/snapshot (เนเธเนเธเธฑเธเธเธฒเธฃเธชเนเธเธเธญเธเธฃเธญเธ เนเธกเนเนเธซเนเธเธฃเธฐเธ—เธเธฃเธญเธ escalation เธฃเธฒเธขเธชเธฑเธเธ”เธฒเธซเน)"""
    today = today or today_th()
    holidays = schedule.load_holidays(HOLIDAYS_FILE)
    if not force and not schedule.is_send_day(today, holidays):
        return {"status": "skipped", "reason": "เนเธกเนเนเธเนเธงเธฑเธเธชเนเธ (เนเธกเนเนเธเนเธงเธฑเธเธ—เธณเธเธฒเธเนเธฃเธเธเธญเธเธชเธฑเธเธ”เธฒเธซเน)", "today": today.isoformat()}

    sla = int(os.environ.get("TG_SLA_DAYS", core.SLA_DAYS_DEFAULT))
    mail_max_items = int(os.environ.get("TG_MAIL_MAX_ITEMS", core.MAIL_MAX_ITEMS_DEFAULT))
    if items is None:
        from azure.identity import DefaultAzureCredential

        from .queries import fetch_items

        items = fetch_items(DefaultAzureCredential(), os.environ.get("TG_ASSIGNMENT_NAME", "rg-tag-governance-audit"), _split(os.environ.get("TG_SUBSCRIPTION_IDS", "")))
    items = filter_scope(items, os.environ.get("TG_RG_NAME_REGEX", ""))
    if store is None:
        from .store import BlobStore

        store = BlobStore(os.environ["AzureWebJobsStorage"])

    state = store.get("state.json") or core.empty_state()
    email, new_state, summary = core.run_report(
        items, state, today, sla, os.environ.get("TG_WORKBOOK_URL", ""), mail_max_items
    )
    mail_enabled = os.environ.get("TG_MAIL_ENABLED", "true").strip().lower() not in ("false", "0", "no")
    result = {"status": "ok", "today": today.isoformat(), "summary": summary, "dry_run": dry_run, "mail_enabled": mail_enabled, "persist": persist}

    if email is None:
        result["email"] = "ไม่ส่ง (ทุกรายการผ่านแล้ว หรือเหลือแต่รายการที่รอ Policy ตรวจซ้ำ)"
    else:
        to = _split(os.environ.get("TG_MAIL_TO", ""))
        cc = _split(os.environ.get("TG_MAIL_CC", ""))
        if email["cc_managers"]:
            cc += [c for c in _split(os.environ.get("TG_MAIL_CC_ESCALATION", "")) if c.lower() not in {x.lower() for x in cc}]
        result["email"] = {"to": to, "cc": cc, "subject": email["subject"]}
        if dry_run:
            result["email"]["text_preview"] = email["text"]
        elif not mail_enabled:
            # เธเนเธงเธเน€เธเนเธ snapshot เธเนเธญเธเน€เธฃเธดเนเธกเธชเนเธเน€เธกเธฅ: เนเธกเนเธชเนเธ เนเธฅเธฐเนเธกเนเธเธฑเธเธ—เธถเธเธงเนเธฒ "เธขเธเธฃเธฐเธ”เธฑเธเนเธฅเนเธง" (เธเธฑเธเธเธฑเนเธ 2 เน€เธเธดเธ”เนเธ”เธขเธ—เธตเนเธขเธฑเธเนเธกเนเน€เธเธขเนเธเนเธ)
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
