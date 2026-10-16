"""สร้างไฟล์ HTML ตัวอย่างอีเมลจากข้อมูลจำลอง เพื่อดูหน้าตาโดยไม่ต้อง deploy

    python scripts/preview_email.py               # เขียน email-preview.html
    python scripts/preview_email.py out.html
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "function"))

from tag_governance import core  # noqa: E402
from tag_governance.queries import WHO_ASK, WHO_FIND, WHO_FIX  # noqa: E402

TODAY = date(2026, 10, 19)


def _it(name, kind, rg, cause, detail, owner, who):
    return {"resource_id": f"/x/{name.lower()}", "kind": kind, "name": name, "rg_name": rg, "cause": cause, "detail": detail, "owner_value": owner, "who": who}


RG, VM = "Resource Group", "Virtual Machine"
ITEMS = [
    _it("D901RGSI08", RG, "D901RGSI08", "owner รูปแบบผิด", "owner รูปแบบผิด", "a,bob@kubota.com", WHO_FIX),
    _it("P740RGSI01", RG, "P740RGSI01", "owner รูปแบบผิด", "owner รูปแบบผิด, environment ค่าไม่ถูก: prod", "kamonphan.kan@dome.tu.ac.th", WHO_FIX),
    _it("D901RGSI02", RG, "D901RGSI02", "tag อื่นไม่ครบ", "ไม่มี department", "a@kubota.com,bob@kubota.com", WHO_ASK),
    _it("P901RGSI04", RG, "P901RGSI04", "tag อื่นไม่ครบ", "ไม่มี project, ไม่มี environment", "alice@kubota.com,bob@kubota.com", WHO_ASK),
    _it("vm-owner", VM, "P901RGSI04", "tag อื่นไม่ครบ", "ไม่มี project", "alice@kubota.com", WHO_ASK),
    _it("T901RGSI05", RG, "T901RGSI05", "ไม่มี owner tag", "ไม่มี owner, ไม่มี department", "", WHO_FIND),
    _it("P730RGSI01", RG, "P730RGSI01", "ไม่มี tag เลย", "ไม่มี tag เลย", "", WHO_FIND),
    _it("vm-missing-tags", VM, "D901RGSI02", "ไม่มี owner tag", "ไม่มี owner", "", WHO_FIND),
]

# อายุต่างกันเพื่อให้เห็นทุกสถานะ: ใหม่ / ใกล้ SLA / เกิน SLA (แจ้งครั้งแรก) / ยกระดับ
FIRST_SEEN = {"P730RGSI01": 35, "T901RGSI05": 21, "D901RGSI08": 14, "D901RGSI02": 9, "P901RGSI04": 7, "P740RGSI01": 3}
ESCALATED = {"P730RGSI01": 7}


def main(out: Path) -> None:
    state = {"items": {}, "last_run": (TODAY - timedelta(days=7)).isoformat()}
    for it in ITEMS:
        if it["name"] in FIRST_SEEN:
            esc = ESCALATED.get(it["name"])
            state["items"][it["resource_id"]] = {
                "first_seen": (TODAY - timedelta(days=FIRST_SEEN[it["name"]])).isoformat(),
                "escalated_at": (TODAY - timedelta(days=esc)).isoformat() if esc else None,
                "kind": it["kind"], "name": it["name"],
            }
    state["items"]["/x/old-rg"] = {"first_seen": "2026-09-01", "escalated_at": None, "kind": RG, "name": "D901RGSI01"}
    email, _, summary = core.run_report(ITEMS, state, TODAY, 14, "https://portal.azure.com/#workbook")
    out.write_text(
        f"<!doctype html><meta charset='utf-8'><title>{email['subject']}</title>"
        f"<p style='font:13px sans-serif;color:#666;margin:8px'>Subject: {email['subject']}</p>{email['html']}",
        encoding="utf-8",
    )
    out.with_suffix(".txt").write_text(email["text"], encoding="utf-8")
    print(f"เขียน {out} และ {out.with_suffix('.txt')} · {summary}")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path("email-preview.html"))
