import json
import logging
from datetime import date

import azure.functions as func

from tag_governance import runner

app = func.FunctionApp()


# ทุกวันจันทร์-ศุกร์ 09:00 เวลาไทย (= 02:00 UTC) แต่ส่งเมลเฉพาะ "วันทำงานแรกของสัปดาห์"
# (ถ้าจันทร์เป็นวันหยุด จะส่งวันอังคารแทน) ตรรกะอยู่ใน schedule.is_send_day
@app.timer_trigger(schedule="0 0 2 * * 1-5", arg_name="timer", run_on_startup=False, use_monitor=True)
def weekly_report(timer: func.TimerRequest) -> None:
    result = runner.run(dry_run=False)
    logging.info("weekly_report: %s", json.dumps(result, ensure_ascii=False, default=str))


# ปิดเป็นค่าเริ่มต้น: ตั้ง TG_HTTP_ENABLED=true เฉพาะตอนทดสอบ แล้วปิดกลับ
# เรียกทดสอบมือ: GET /api/run?dry_run=1&force=1&today=2026-10-19  (ต้องมี function key)
# ค่าเริ่มต้น dry_run=1 = ปลอดภัย ไม่ส่งเมล ไม่บันทึก state; ส่งจริงต้องใส่ dry_run=0
@app.route(route="run", auth_level=func.AuthLevel.FUNCTION, methods=["GET", "POST"])
def run_now(req: func.HttpRequest) -> func.HttpResponse:
    if not runner.http_enabled():
        return func.HttpResponse("not found", status_code=404)
    dry = req.params.get("dry_run", "1") not in ("0", "false", "False")
    force = req.params.get("force", "0") in ("1", "true", "True")
    t = req.params.get("today")
    today = date.fromisoformat(t) if t else None
    try:
        result = runner.run(today=today, dry_run=dry, force=force)
    except Exception as e:
        # ส่งข้อความ error กลับไปด้วย (endpoint นี้ต้องมี function key และเปิดเฉพาะตอนทดสอบ) จะได้ไม่ต้องไปเปิด log
        logging.exception("run_now failed")
        return func.HttpResponse(f"{type(e).__name__}: {e}", status_code=500, mimetype="text/plain; charset=utf-8")
    return func.HttpResponse(json.dumps(result, ensure_ascii=False, indent=2, default=str), mimetype="application/json")


# ส่งเมลรายงานทันทีตอนไหนก็ได้ (ไม่ต้องรอวันทำงานแรกของสัปดาห์): POST /api/send  (ต้องมี function key)
# ปิดเป็นค่าเริ่มต้น: ตั้ง TG_MANUAL_SEND_ENABLED=true เพื่อเปิด และยังเคารพ TG_MAIL_ENABLED
# ไม่บันทึก state/snapshot เพื่อไม่ให้การส่งนอกรอบเลื่อนรอบ escalation (ขั้น 1 -> ขั้น 2) ของรายงานประจำสัปดาห์
@app.route(route="send", auth_level=func.AuthLevel.FUNCTION, methods=["POST"])
def send_now(req: func.HttpRequest) -> func.HttpResponse:
    if not runner.manual_send_enabled():
        return func.HttpResponse("not found", status_code=404)
    try:
        result = runner.run(dry_run=False, force=True, persist=False)
    except Exception as e:
        logging.exception("send_now failed")
        return func.HttpResponse(f"{type(e).__name__}: {e}", status_code=500, mimetype="text/plain; charset=utf-8")
    logging.info("send_now: %s", json.dumps(result, ensure_ascii=False, default=str))
    return func.HttpResponse(json.dumps(result, ensure_ascii=False, indent=2, default=str), mimetype="application/json")
