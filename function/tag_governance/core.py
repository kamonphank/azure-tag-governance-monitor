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
from datetime import date, datetime, timedelta, timezone

from .queries import WHO_PENDING

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
# อีเมลใช้ inline style และ layout แบบ table ทั้งหมด เพื่อให้แสดงผลเหมือนกันใน Outlook และ Gmail

WHO_GROUPS = [  # (ค่า who จาก queries.py, คำอธิบาย, สีพื้น, สีตัวอักษร) สีชุดเดียวกับ Workbook
    ("Cloud team แก้ได้", "tag มีค่าแล้วแต่รูปแบบหรือค่าไม่ถูก แก้ได้เลย", "#e6f4ea", "#137333"),
    ("ถาม owner", "มี owner แต่ขาด tag อื่น ติดต่อ owner เพื่อขอข้อมูล", "#fef3e0", "#b45309"),
    ("หา owner ก่อน", "ไม่มี owner ที่ติดต่อได้ ต้องหาเจ้าของ resource ก่อน", "#fce8e6", "#c5221f"),
]
_OTHER_GROUP = ("อื่นๆ", "", "#f1f3f4", "#3c4043")

_FONT = "font-family:'Segoe UI',Tahoma,Arial,sans-serif"
_INK, _MUTED, _LINE, _SOFT = "#1f2937", "#6b7280", "#e5e7eb", "#f9fafb"


def _e(v) -> str:
    return html.escape(str(v if v is not None else ""))


def _pill(text: str, bg: str, fg: str) -> str:
    return (
        f'<span style="display:inline-block;padding:2px 8px;border-radius:10px;background:{bg};color:{fg};'
        f'font-size:12px;font-weight:600;white-space:nowrap">{_e(text)}</span>'
    )


def _group_of(who: str) -> tuple:
    return next((g for g in WHO_GROUPS if g[0] == who), _OTHER_GROUP)


def _detail(r: dict) -> str:
    return r.get("detail") or r.get("cause") or ""


def _owners(r: dict) -> list[str]:
    return [o.strip() for o in (r.get("owner_value") or "").split(",") if o.strip()]


def _evaluated(r: dict) -> str:
    """เวลาที่ Policy ประเมินล่าสุด แปลงเป็นเวลาไทย เช่น "16/10 14:12" (ว่างถ้าไม่มีข้อมูล)"""
    v = r.get("evaluated_at") or ""
    try:
        t = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return ""
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return t.astimezone(timezone(timedelta(hours=7))).strftime("%d/%m %H:%M")


def _age_html(age, sla_days: int) -> str:
    if age == "" or age is None:
        return ""
    color, weight = (_MUTED, "400")
    if age >= sla_days:
        color, weight = ("#c5221f", "700")
    elif age >= sla_days / 2:
        color, weight = ("#b45309", "600")
    return f'<span style="color:{color};font-weight:{weight}">{_e(age)}</span>'


def _table(rows: list[dict], sla_days: int, new_ids: set[str]) -> str:
    th_style = f"text-align:left;padding:8px 10px;font-size:12px;font-weight:600;color:{_MUTED};border-bottom:1px solid {_LINE};background:{_SOFT}"
    cols = (("รายการ", "28%", ""), ("สิ่งที่ไม่ผ่าน", "34%", ""), ("owner", "28%", ""), ("อายุ (วัน)", "10%", ";text-align:right;white-space:nowrap"))
    head = "".join(f'<th width="{w}" style="{th_style}{extra}">{h}</th>' for h, w, extra in cols)
    body = ""
    for r in rows:
        td = f"padding:10px;border-bottom:1px solid {_LINE};vertical-align:top;font-size:14px;color:{_INK}"
        where = "Resource Group" if r.get("kind") == "Resource Group" else f"VM · {r.get('rg_name') or '-'}"
        if _evaluated(r):
            where += f" · ตรวจ {_evaluated(r)}"
        new = " " + _pill("ใหม่", "#e8f0fe", "#1a56db") if r.get("resource_id") in new_ids else ""
        owners = "<br>".join(_e(o) for o in _owners(r)) or f'<span style="color:{_MUTED}">-</span>'
        body += (
            "<tr>"
            f'<td style="{td}"><div style="font-weight:600">{_e(r.get("name"))}{new}</div>'
            f'<div style="font-size:12px;color:{_MUTED};margin-top:2px;white-space:nowrap">{_e(where)}</div></td>'
            f'<td style="{td}">{_e(_detail(r))}</td>'
            f'<td style="{td};font-size:13px">{owners}</td>'
            f'<td style="{td};text-align:right">{_age_html(r.get("age_days"), sla_days)}</td>'
            "</tr>"
        )
    return (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'style="border-collapse:collapse;border:1px solid {_LINE};background:#ffffff;{_FONT}"><tr>{head}</tr>{body}</table>'
    )


def _section(title_html: str, note: str, table: str) -> str:
    note_html = f'<div style="font-size:13px;color:{_MUTED};margin:4px 0 0">{_e(note)}</div>' if note else ""
    return f'<div style="margin:28px 0 0"><div style="font-size:16px;font-weight:600;color:{_INK}">{title_html}</div>{note_html}<div style="margin-top:10px">{table}</div></div>'


def _callout(title: str, note: str, table: str, bg: str, fg: str) -> str:
    return (
        f'<div style="margin:24px 0 0;padding:14px 16px;background:{bg};border-left:4px solid {fg}">'
        f'<div style="font-size:15px;font-weight:700;color:{fg}">{_e(title)}</div>'
        f'<div style="font-size:13px;color:{_INK};margin:4px 0 10px">{_e(note)}</div>{table}</div>'
    )


def _kpis(cells: list[tuple[str, int, str]]) -> str:
    tds = ""
    for label, n, color in cells:
        tds += (
            f'<td width="{100 // len(cells)}%" style="padding:14px 16px;border:1px solid {_LINE};background:#ffffff">'
            f'<div style="font-size:12px;color:{_MUTED}">{_e(label)}</div>'
            f'<div style="font-size:28px;font-weight:700;line-height:1.2;color:{color}">{n}</div></td>'
        )
    return f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;margin-top:16px"><tr>{tds}</tr></table>'


def _button(url: str, text: str) -> str:
    return (
        f'<table role="presentation" cellpadding="0" cellspacing="0" style="margin-top:20px"><tr>'
        f'<td style="background:#0f6cbd;border-radius:4px"><a href="{_e(url)}" '
        f'style="display:inline-block;padding:10px 18px;color:#ffffff;text-decoration:none;font-size:14px;font-weight:600;{_FONT}">{_e(text)}</a></td>'
        f"</tr></table>"
    )


def _text_rows(rows: list[dict], new_ids: set[str]) -> str:
    out = []
    for r in rows:
        where = "RG" if r.get("kind") == "Resource Group" else f"VM ใน {r.get('rg_name') or '-'}"
        new = " [ใหม่]" if r.get("resource_id") in new_ids else ""
        ev = f" | ตรวจ {_evaluated(r)}" if _evaluated(r) else ""
        out.append(f"  - {r['name']} ({where}){new} | {_detail(r)}{ev} | owner: {', '.join(_owners(r)) or '-'} | อายุ {r['age_days']} วัน")
    return "\n".join(out)


def build_email(items_aged, appeared, resolved, stage1, stage2, today: date, sla_days: int, workbook_url: str = "", pending=()) -> dict:
    """items_aged = รายการที่ต้องทำ (ไม่รวม pending = แก้ tag แล้ว รอ Policy ตรวจซ้ำ ซึ่งแสดงแยกท้ายเมล)"""
    new_ids = {i["resource_id"] for i in appeared}
    appeared = [i for i in items_aged if i["resource_id"] in new_ids]
    n_rg = sum(1 for i in items_aged if i["kind"] == "Resource Group")
    n_vm = len(items_aged) - n_rg
    n_over = sum(1 for i in items_aged if i["age_days"] >= sla_days)
    tag = "[ESCALATION] " if stage2 else ""
    subject = f"{tag}[Tag Governance] ค้าง {len(items_aged)} รายการ (RG {n_rg} / VM {n_vm}) · ใหม่ {len(appeared)} · แก้แล้ว {len(resolved)} · {today.isoformat()}"

    parts: list[str] = []
    txt: list[str] = []

    # ---- หัวเมล
    parts.append(
        f'<div style="font-size:12px;font-weight:600;letter-spacing:.5px;color:{_MUTED}">TAG GOVERNANCE · สรุปประจำสัปดาห์ {today.isoformat()}</div>'
        f'<div style="font-size:22px;font-weight:700;color:{_INK};margin-top:6px">ยังไม่ผ่าน {len(items_aged)} รายการ '
        f'<span style="font-size:15px;font-weight:400;color:{_MUTED}">(RG {n_rg} · VM {n_vm})</span></div>'
    )
    parts.append(
        _kpis(
            [
                ("ค้างทั้งหมด", len(items_aged), _INK),
                ("ใหม่รอบนี้", len(appeared), "#1a56db" if appeared else _INK),
                ("แก้แล้วตั้งแต่รอบก่อน", len(resolved), "#137333" if resolved else _INK),
                (f"ค้างเกิน {sla_days} วัน", n_over, "#c5221f" if n_over else _INK),
            ]
        )
    )
    txt.append(
        f"Tag Governance · สรุปประจำสัปดาห์ {today.isoformat()}\n"
        f"ยังไม่ผ่าน {len(items_aged)} รายการ (RG {n_rg}, VM {n_vm}) · ใหม่ {len(appeared)} · แก้แล้ว {len(resolved)} · ค้างเกิน {sla_days} วัน {n_over}"
    )

    groups: dict[str, list[dict]] = {}
    for it in items_aged:
        groups.setdefault(_group_of(it.get("who", ""))[0], []).append(it)
    order = [g for g in WHO_GROUPS + [_OTHER_GROUP] if g[0] in groups]
    parts.append(
        '<div style="margin-top:14px;font-size:13px">'
        + " &nbsp; ".join(f"{_pill(g[0], g[2], g[3])} <b style='color:{_INK}'>{len(groups[g[0]])}</b>" for g in order)
        + "</div>"
    )
    txt.append(" · ".join(f"{g[0]} {len(groups[g[0]])}" for g in order))

    if workbook_url:
        parts.append(_button(workbook_url, "เปิด Workbook เพื่อดูรายละเอียดและ Export รายชื่อ owner"))
        txt.append(f"Workbook: {workbook_url}")

    # ---- รายการที่ต้องยกระดับ (ซ้ำกับตารางด้านล่างโดยตั้งใจ เพราะเป็นเรื่องที่ต้องเห็นก่อน)
    if stage2:
        note = f"ค้างเกิน {sla_days} วัน และยังไม่แก้หลังแจ้งรอบก่อน · Cc ผู้จัดการตามที่ตั้งค่าไว้"
        parts.append(_callout(f"ยกระดับถึงผู้จัดการ ({len(stage2)})", note, _table(stage2, sla_days, new_ids), "#fce8e6", "#c5221f"))
        txt.append(f"ยกระดับถึงผู้จัดการ ({len(stage2)})\n{note}\n" + _text_rows(stage2, new_ids))
    if stage1:
        note = "แจ้งครั้งแรก · ถ้ายังค้างในรอบหน้า จะ Cc ผู้จัดการ"
        parts.append(_callout(f"ค้างเกิน {sla_days} วัน ({len(stage1)})", note, _table(stage1, sla_days, new_ids), "#fef3e0", "#b45309"))
        txt.append(f"ค้างเกิน {sla_days} วัน ({len(stage1)})\n{note}\n" + _text_rows(stage1, new_ids))

    # ---- รายการทั้งหมด แยกตามสิ่งที่ต้องทำ
    for who, desc, bg, fg in order:
        rows = groups[who]
        title = f"{_pill(who, bg, fg)} <span style='margin-left:4px'>{len(rows)} รายการ</span>"
        parts.append(_section(title, desc, _table(rows, sla_days, new_ids)))
        txt.append(f"{who} ({len(rows)})" + (f" - {desc}" if desc else "") + "\n" + _text_rows(rows, new_ids))

    if pending:
        names = ", ".join(f"{_e(r['name'])} <span style='color:{_MUTED}'>({'RG' if r['kind'] == 'Resource Group' else 'VM'})</span>" for r in pending)
        parts.append(
            f'<div style="margin:28px 0 0;padding:12px 16px;background:{_SOFT};border-left:4px solid #9ca3af;font-size:14px;color:{_INK}">'
            f'<b>แก้ tag แล้ว รอ Policy ตรวจซ้ำ ({len(pending)})</b><br>{names}'
            f'<div style="font-size:12px;color:{_MUTED};margin-top:4px">ไม่ต้องทำอะไร ไม่นับรวมในตัวเลขด้านบน · ถ้า Policy ยืนยันว่าผ่าน จะย้ายไป "แก้แล้ว" ในรอบหน้า</div></div>'
        )
        txt.append(f"แก้ tag แล้ว รอ Policy ตรวจซ้ำ ({len(pending)}) - ไม่ต้องทำอะไร\n" + "\n".join(f"  - {r['name']} ({r['kind']})" for r in pending))

    if resolved:
        names = ", ".join(f"{_e(r['name'])} <span style='color:{_MUTED}'>({'RG' if r['kind'] == 'Resource Group' else 'VM'})</span>" for r in resolved)
        parts.append(
            f'<div style="margin:28px 0 0;padding:12px 16px;background:#e6f4ea;border-left:4px solid #137333;font-size:14px;color:{_INK}">'
            f'<b style="color:#137333">แก้แล้วตั้งแต่รอบก่อน ({len(resolved)})</b><br>{names}</div>'
        )
        txt.append(f"แก้แล้วตั้งแต่รอบก่อน ({len(resolved)})\n" + "\n".join(f"  - {r['name']} ({r['kind']})" for r in resolved))

    # ---- ท้ายเมล
    legend = "".join(f"<div style='margin-top:4px'><b>{_e(w)}</b> - {_e(d)}</div>" for w, d, _, _ in WHO_GROUPS)
    parts.append(
        f'<div style="margin-top:32px;padding-top:14px;border-top:1px solid {_LINE};font-size:12px;color:{_MUTED};line-height:1.6">'
        f"{legend}"
        "<div style='margin-top:8px'>ตรวจ = เวลาที่ Azure Policy ประเมินล่าสุด · รายการที่แก้ tag หลังเวลานั้นจะถูกแยกไปที่ \"รอ Policy ตรวจซ้ำ\" เอง "
        "ถ้าค้างนาน สั่งตรวจทันทีด้วย <code>az policy state trigger-scan --resource-group &lt;ชื่อ RG&gt;</code></div>"
        f"<div style='margin-top:8px'>อายุ = จำนวนวันนับจากวันที่ระบบพบรายการครั้งแรก · ค้างเกิน {sla_days} วันจะถูกแจ้ง และถ้ายังค้างในรอบถัดไปจะ Cc ผู้จัดการ</div>"
        "<div style='margin-top:8px'>ส่งอัตโนมัติจาก Azure Function ทุกวันทำงานแรกของสัปดาห์ (ไม่ส่งเมื่อทุกรายการผ่านแล้ว)</div>"
        "</div>"
    )

    html_body = (
        f'<div style="margin:0;padding:24px 12px;background:#f3f4f6;{_FONT}">'
        f'<table role="presentation" align="center" width="100%" cellpadding="0" cellspacing="0" style="max-width:760px;margin:0 auto;border-collapse:collapse">'
        f'<tr><td style="background:#ffffff;padding:28px 28px 24px;border:1px solid {_LINE};border-top:4px solid #0f6cbd;{_FONT}">'
        + "".join(parts)
        + "</td></tr></table></div>"
    )
    return {
        "subject": subject,
        "html": html_body,
        "text": "\n\n".join(txt) + "\n",
        "cc_managers": bool(stage2),
    }


def run_report(items: list[dict], state: dict, today: date, sla_days: int = SLA_DAYS_DEFAULT, workbook_url: str = ""):
    """ฟังก์ชันเดียวที่รวมขั้นตอนทั้งหมด คืน (email|None, state_ใหม่, สรุปตัวเลข)
    รายการที่รอ Policy ตรวจซ้ำยังถูกเก็บใน state (อายุนับต่อ) แต่ไม่นับรวม ไม่ escalate และไม่ทำให้ต้องส่งเมล"""
    state1, appeared, resolved = update_state(items, state, today)
    aged = with_age(items, state1, today)
    pending = [i for i in aged if i.get("who") == WHO_PENDING]
    active = [i for i in aged if i.get("who") != WHO_PENDING]
    stage1, stage2, state2 = classify(active, state1, today, sla_days)
    summary = {
        "total": len(active), "new": sum(1 for i in appeared if i.get("who") != WHO_PENDING), "resolved": len(resolved),
        "stage1": len(stage1), "stage2": len(stage2), "pending": len(pending),
    }
    if not should_send(active):
        return None, state2, summary
    email = build_email(active, appeared, resolved, stage1, stage2, today, sla_days, workbook_url, pending)
    return email, state2, summary
