"""ตรรกะหลัก (ไม่พึ่ง Azure) ทดสอบได้ด้วย pytest

state = {"items": {resource_id: {"first_seen": "YYYY-MM-DD", "escalated_at": "YYYY-MM-DD"|None,
                                 "kind":..., "name":...}}, "last_run": "YYYY-MM-DD"|None}

กติกา escalation (ตรวจทุกวันจันทร์):
  อายุ = วันนี้ - first_seen (วัน)
  ขั้น 1: อายุ >= SLA และยังไม่เคยถูกยกระดับ  -> แจ้งผู้รับเมล (To) สัปดาห์นี้ (บันทึก escalated_at)
  ขั้น 2: อายุ >= SLA และเคยยกระดับในสัปดาห์ก่อนหน้าแล้วแต่ยังค้าง -> Cc ผู้จัดการเพิ่ม (TG_MAIL_CC_ESCALATION)
"""
from __future__ import annotations

import copy
import html
from datetime import date

SLA_DAYS_DEFAULT = 14


def empty_state() -> dict:
    return {"items": {}, "last_run": None}


def update_state(items: list[dict], state: dict, today: date) -> tuple[dict, list[dict], list[dict]]:
    """คืน (state_ใหม่, รายการใหม่, รายการที่แก้แล้ว) โดยไม่แก้ state เดิม"""
    old = state.get("items", {})
    new_items: dict[str, dict] = {}
    appeared: list[dict] = []
    current_ids = set()
    for it in items:
        rid = it["resource_id"]
        current_ids.add(rid)
        prev = old.get(rid)
        if prev:
            rec = dict(prev)
            rec["kind"], rec["name"] = it["kind"], it["name"]
        else:
            rec = {"first_seen": today.isoformat(), "escalated_at": None, "kind": it["kind"], "name": it["name"]}
            appeared.append(it)
        new_items[rid] = rec
    resolved = [
        {"resource_id": rid, **rec} for rid, rec in old.items() if rid not in current_ids
    ]
    return {"items": new_items, "last_run": today.isoformat()}, appeared, resolved


def with_age(items: list[dict], state: dict, today: date) -> list[dict]:
    out = []
    for it in items:
        rec = state["items"].get(it["resource_id"])
        first = date.fromisoformat(rec["first_seen"]) if rec else today
        out.append({**it, "first_seen": first.isoformat(), "age_days": (today - first).days})
    out.sort(key=lambda x: (-x["age_days"], x["kind"], x["name"]))
    return out


def classify(items_aged: list[dict], state: dict, today: date, sla_days: int = SLA_DAYS_DEFAULT):
    """คืน (ขั้น1, ขั้น2, state ที่บันทึก escalated_at แล้ว)"""
    state = copy.deepcopy(state)
    stage1, stage2 = [], []
    for it in items_aged:
        if it["age_days"] < sla_days:
            continue
        rec = state["items"][it["resource_id"]]
        esc = rec.get("escalated_at")
        if esc is None:
            stage1.append(it)
            rec["escalated_at"] = today.isoformat()
        elif date.fromisoformat(esc) < today:
            stage2.append(it)
    return stage1, stage2, state


def should_send(items: list[dict]) -> bool:
    return len(items) > 0


# ---------------------------------------------------------------- email

_TH_COLS = [("ชื่อ", "name"), ("ประเภท", "kind"), ("RG", "rg_name"), ("สาเหตุ", "cause"), ("owner", "owner_value"), ("อายุ (วัน)", "age_days")]


def _table(rows: list[dict]) -> str:
    th = "".join(f'<th style="text-align:left;padding:6px 10px;border-bottom:2px solid #ccc">{h}</th>' for h, _ in _TH_COLS)
    body = ""
    for r in rows:
        tds = "".join(
            f'<td style="padding:6px 10px;border-bottom:1px solid #eee">{html.escape(str(r.get(k, "")))}</td>' for _, k in _TH_COLS
        )
        body += f"<tr>{tds}</tr>"
    return f'<table style="border-collapse:collapse;font-size:14px"><tr>{th}</tr>{body}</table>'


def _text_rows(rows: list[dict]) -> str:
    return "\n".join(
        f"  - {r['name']} ({r['kind']}) | {r['cause']} | owner: {r['owner_value'] or '-'} | อายุ {r['age_days']} วัน" for r in rows
    )


def build_email(items_aged, appeared, resolved, stage1, stage2, today: date, sla_days: int, workbook_url: str = "") -> dict:
    n_rg = sum(1 for i in items_aged if i["kind"] == "Resource Group")
    n_vm = len(items_aged) - n_rg
    tag = "[ESCALATION] " if stage2 else ""
    subject = f"{tag}[Tag Governance] ค้าง {len(items_aged)} รายการ (RG {n_rg} / VM {n_vm}) · ใหม่ {len(appeared)} · แก้แล้ว {len(resolved)} · {today.isoformat()}"

    sections_html: list[str] = []
    sections_txt: list[str] = []

    def add(title: str, rows: list[dict], note: str = ""):
        if not rows:
            return
        sections_html.append(f"<h3 style='margin:20px 0 6px'>{html.escape(title)} ({len(rows)})</h3>" + (f"<p style='margin:0 0 6px;color:#555'>{html.escape(note)}</p>" if note else "") + _table(rows))
        sections_txt.append(f"{title} ({len(rows)})" + (f"\n{note}" if note else "") + "\n" + _text_rows(rows))

    add(f"ยกระดับถึงผู้จัดการ: ค้างเกิน {sla_days} วัน และยังไม่แก้หลังแจ้งสัปดาห์ก่อน", stage2, "Cc: ผู้จัดการตามที่ตั้งค่าไว้")
    add(f"ค้างเกิน {sla_days} วัน (แจ้งครั้งแรก)", stage1, "ถ้ายังค้างในสัปดาห์หน้า จะ Cc ผู้จัดการ")
    add("รายการใหม่สัปดาห์นี้", with_age(appeared, {"items": {i["resource_id"]: {"first_seen": today.isoformat()} for i in appeared}}, today))
    add("แก้แล้วตั้งแต่สัปดาห์ก่อน", [{"name": r["name"], "kind": r["kind"], "rg_name": "", "cause": "", "owner_value": "", "age_days": ""} for r in resolved])
    add("รายการที่ยังค้างทั้งหมด (เรียงตามอายุ)", items_aged)

    link_html = f'<p><a href="{html.escape(workbook_url)}">เปิด Workbook เพื่อดู/Export รายชื่อ owner</a></p>' if workbook_url else ""
    link_txt = f"\nWorkbook: {workbook_url}\n" if workbook_url else ""
    head_html = (
        f"<p>สรุปสถานะ tag governance วันที่ {today.isoformat()}<br>"
        f"ค้างทั้งหมด <b>{len(items_aged)}</b> (RG {n_rg}, VM {n_vm}) · ใหม่ {len(appeared)} · แก้แล้ว {len(resolved)}</p>"
    )
    head_txt = f"สรุปสถานะ tag governance วันที่ {today.isoformat()}\nค้างทั้งหมด {len(items_aged)} (RG {n_rg}, VM {n_vm}) · ใหม่ {len(appeared)} · แก้แล้ว {len(resolved)}\n"
    foot_html = "<p style='color:#777;font-size:12px'>ส่งอัตโนมัติจาก Azure Function (ไม่ส่งเมื่อทุกรายการผ่านแล้ว)</p>"
    return {
        "subject": subject,
        "html": f"<div style='font-family:Segoe UI,Tahoma,sans-serif'>{head_html}{link_html}{''.join(sections_html)}{foot_html}</div>",
        "text": head_txt + link_txt + "\n\n".join(sections_txt),
        "cc_managers": bool(stage2),
    }


def run_report(items: list[dict], state: dict, today: date, sla_days: int = SLA_DAYS_DEFAULT, workbook_url: str = ""):
    """ฟังก์ชันเดียวที่รวมขั้นตอนทั้งหมด คืน (email|None, state_ใหม่, สรุปตัวเลข)"""
    state1, appeared, resolved = update_state(items, state, today)
    aged = with_age(items, state1, today)
    stage1, stage2, state2 = classify(aged, state1, today, sla_days)
    summary = {
        "total": len(aged), "new": len(appeared), "resolved": len(resolved),
        "stage1": len(stage1), "stage2": len(stage2),
    }
    if not should_send(aged):
        return None, state2, summary
    email = build_email(aged, appeared, resolved, stage1, stage2, today, sla_days, workbook_url)
    return email, state2, summary
