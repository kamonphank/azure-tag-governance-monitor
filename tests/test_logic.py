from datetime import date

import pytest

from tag_governance import core, queries, runner, schedule
from tag_governance.store import LocalStore


def item(rid, name="x", kind="Resource Group", cause="tag อื่นไม่ครบ", owner="a@example.com"):
    return {"resource_id": rid, "kind": kind, "name": name, "rg_name": name, "cause": cause, "owner_value": owner, "who": "Cloud team แก้ได้"}


# ---------------- schedule ----------------
def test_normal_monday_is_send_day():
    assert schedule.is_send_day(date(2026, 10, 19), set())  # จันทร์
    assert not schedule.is_send_day(date(2026, 10, 20), set())  # อังคาร ปกติไม่ส่ง


def test_weekend_never():
    assert not schedule.is_send_day(date(2026, 10, 17), set())
    assert not schedule.is_send_day(date(2026, 10, 18), set())


def test_monday_holiday_moves_to_tuesday():
    hol = {date(2026, 10, 19)}
    assert not schedule.is_send_day(date(2026, 10, 19), hol)
    assert schedule.is_send_day(date(2026, 10, 20), hol)
    assert not schedule.is_send_day(date(2026, 10, 21), hol)


def test_mon_tue_holiday_moves_to_wednesday():
    hol = {date(2026, 10, 19), date(2026, 10, 20)}
    assert schedule.is_send_day(date(2026, 10, 21), hol)
    assert not schedule.is_send_day(date(2026, 10, 22), hol)


def test_real_calendar_oct_13_holiday_does_not_affect_monday_12():
    hol = schedule.load_holidays(runner.HOLIDAYS_FILE)
    assert date(2026, 10, 13) in hol
    assert schedule.is_send_day(date(2026, 10, 12), hol)
    assert not schedule.is_send_day(date(2026, 10, 13), hol)


# ---------------- state / age / escalation ----------------
def test_first_seen_and_age():
    s, appeared, resolved = core.update_state([item("a"), item("b")], core.empty_state(), date(2026, 10, 19))
    assert len(appeared) == 2 and resolved == []
    aged = core.with_age([item("a")], s, date(2026, 11, 2))
    assert aged[0]["age_days"] == 14


def test_resolved_detected_and_first_seen_kept():
    s1, _, _ = core.update_state([item("a"), item("b")], core.empty_state(), date(2026, 10, 19))
    s2, appeared, resolved = core.update_state([item("a"), item("c")], s1, date(2026, 10, 26))
    assert [i["resource_id"] for i in appeared] == ["c"]
    assert [r["resource_id"] for r in resolved] == ["b"]
    assert s2["items"]["a"]["first_seen"] == "2026-10-19"
    assert "b" not in s2["items"]


def test_reappearing_item_restarts_age():
    s1, _, _ = core.update_state([item("a")], core.empty_state(), date(2026, 10, 19))
    s2, _, _ = core.update_state([], s1, date(2026, 10, 26))
    s3, appeared, _ = core.update_state([item("a")], s2, date(2026, 11, 2))
    assert len(appeared) == 1 and s3["items"]["a"]["first_seen"] == "2026-11-02"


def test_escalation_two_stages():
    items = [item("a", "old")]
    state = core.empty_state()
    sends = []
    for d in [date(2026, 10, 19), date(2026, 10, 26), date(2026, 11, 2), date(2026, 11, 9), date(2026, 11, 16)]:
        email, state, summary = core.run_report(items, state, d)
        sends.append((d.isoformat(), summary["stage1"], summary["stage2"], email["cc_managers"]))
    # อายุ 0, 7 -> ไม่ยกระดับ; 14 -> ขั้น1 (ไม่ Cc); 21 -> ขั้น2 (Cc); 28 -> ขั้น2 ซ้ำ (Cc ต่อ)
    assert sends == [
        ("2026-10-19", 0, 0, False),
        ("2026-10-26", 0, 0, False),
        ("2026-11-02", 1, 0, False),
        ("2026-11-09", 0, 1, True),
        ("2026-11-16", 0, 1, True),
    ]


def test_new_item_not_escalated_while_old_one_is():
    state = core.empty_state()
    _, state, _ = core.run_report([item("old")], state, date(2026, 10, 19))
    _, state, _ = core.run_report([item("old")], state, date(2026, 10, 26))
    email, state, s = core.run_report([item("old"), item("new")], state, date(2026, 11, 2))
    assert s["stage1"] == 1 and s["stage2"] == 0 and s["new"] == 1
    assert not email["cc_managers"]


def test_no_email_when_everything_passes():
    email, state, s = core.run_report([], core.empty_state(), date(2026, 10, 19))
    assert email is None and s["total"] == 0


def test_email_content_has_counts_and_escapes_html():
    items = [item("a", name="<script>x</script>", owner="a@example.com,c")]
    email, _, _ = core.run_report(items, core.empty_state(), date(2026, 10, 19), workbook_url="https://portal.azure.com/x")
    assert "<script>" not in email["html"] and "&lt;script&gt;" in email["html"]
    assert "ค้าง 1 รายการ" in email["subject"]
    assert "https://portal.azure.com/x" in email["html"]


def test_subject_marks_escalation():
    state = core.empty_state()
    items = [item("a")]
    for d in [date(2026, 10, 19), date(2026, 11, 2)]:
        _, state, _ = core.run_report(items, state, d)
    email, _, _ = core.run_report(items, state, date(2026, 11, 9))
    assert email["subject"].startswith("[ESCALATION]")


# ---------------- runner (ทั้งสายงาน ใช้ store ในเครื่อง ไม่แตะ Azure) ----------------
@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("TG_MAIL_TO", "pond@example.com")
    monkeypatch.setenv("TG_MAIL_CC_ESCALATION", "m1@example.com;m2@example.com")
    monkeypatch.setenv("TG_ACS_CONNECTION_STRING", "x")
    monkeypatch.setenv("TG_MAIL_SENDER", "s@example.com")
    sent = []
    import tag_governance.mailer as mailer

    monkeypatch.setattr(mailer, "send_email", lambda *a, **k: sent.append(a) or "id-1")
    return sent


def test_runner_dry_run_does_not_send_or_write(tmp_path, env):
    st = LocalStore(tmp_path)
    r = runner.run(today=date(2026, 10, 19), dry_run=True, items=[item("a")], store=st)
    assert r["status"] == "ok" and not env and st.get("state.json") is None


def test_runner_real_run_sends_and_persists(tmp_path, env):
    st = LocalStore(tmp_path)
    r = runner.run(today=date(2026, 10, 19), dry_run=False, items=[item("a")], store=st)
    assert len(env) == 1 and env[0][2] == ["pond@example.com"] and env[0][3] == []
    assert st.get("state.json")["items"]["a"]["first_seen"] == "2026-10-19"
    assert st.get("snapshots/2026-10-19.json")["summary"]["total"] == 1


def test_runner_escalation_adds_cc(tmp_path, env):
    st = LocalStore(tmp_path)
    for d in [date(2026, 10, 19), date(2026, 11, 2), date(2026, 11, 9)]:
        runner.run(today=d, dry_run=False, items=[item("a")], store=st, force=True)
    assert env[-1][3] == ["m1@example.com", "m2@example.com"]
    assert env[-2][3] == []


def test_runner_skips_non_send_day(tmp_path, env):
    r = runner.run(today=date(2026, 10, 21), dry_run=False, items=[item("a")], store=LocalStore(tmp_path))
    assert r["status"] == "skipped" and not env


def test_runner_all_pass_sends_nothing(tmp_path, env):
    r = runner.run(today=date(2026, 10, 19), dry_run=False, items=[], store=LocalStore(tmp_path))
    assert not env and "ไม่ส่ง" in r["email"]


def test_runner_mail_disabled_collects_snapshot_without_sending_or_escalating(tmp_path, env, monkeypatch):
    monkeypatch.setenv("TG_MAIL_ENABLED", "false")
    st = LocalStore(tmp_path)
    for d in [date(2026, 10, 26), date(2026, 11, 9)]:  # วันที่ 9 พ.ย. อายุ 14 วัน แต่ปิดเมลอยู่
        runner.run(today=d, dry_run=False, items=[item("a")], store=st)
    assert not env
    rec = st.get("state.json")["items"]["a"]
    assert rec["first_seen"] == "2026-10-26" and rec["escalated_at"] is None
    # เปิดเมลวันที่ 16 พ.ย. -> ต้องเป็นขั้น 1 (ยังไม่เคยแจ้ง) ไม่ใช่ขั้น 2
    monkeypatch.setenv("TG_MAIL_ENABLED", "true")
    r = runner.run(today=date(2026, 11, 16), dry_run=False, items=[item("a")], store=st)
    assert r["summary"]["stage1"] == 1 and r["summary"]["stage2"] == 0 and env[-1][3] == []


def test_runner_two_recipients_no_cc_when_cc_unset(tmp_path, env, monkeypatch):
    monkeypatch.setenv("TG_MAIL_TO", "pond@example.com, me@example.com")
    monkeypatch.delenv("TG_MAIL_CC_ESCALATION", raising=False)
    st = LocalStore(tmp_path)
    for d in [date(2026, 10, 19), date(2026, 11, 2), date(2026, 11, 9)]:
        runner.run(today=d, dry_run=False, items=[item("a")], store=st, force=True)
    assert env[-1][2] == ["pond@example.com", "me@example.com"]
    assert env[-1][3] == []  # ขั้น 2 แต่ไม่ได้ตั้ง Cc -> ไม่มี Cc


def test_runner_cc_always_plus_escalation_cc(tmp_path, env, monkeypatch):
    monkeypatch.setenv("TG_MAIL_CC", "mod@example.com")
    monkeypatch.setenv("TG_MAIL_CC_ESCALATION", "kae@example.com, MOD@example.com")
    st = LocalStore(tmp_path)
    runner.run(today=date(2026, 10, 19), dry_run=False, items=[item("a")], store=st, force=True)
    assert env[-1][3] == ["mod@example.com"]  # ขั้นปกติ: Cc เฉพาะ TG_MAIL_CC
    for d in [date(2026, 11, 2), date(2026, 11, 9)]:
        runner.run(today=d, dry_run=False, items=[item("a")], store=st, force=True)
    assert env[-1][3] == ["mod@example.com", "kae@example.com"]  # ขั้น 2: เพิ่ม Cc ขั้น 2 โดยไม่ซ้ำ


def test_filter_scope():
    from tag_governance.queries import filter_scope

    its = [{"rg_name": "p706rgsi01"}, {"rg_name": "databricks-rg-x-123"}, {"rg_name": "D711RGSI01"}]
    assert filter_scope(its, "") == its
    assert [i["rg_name"] for i in filter_scope(its, r"^[pd]\d{3}rg")] == ["p706rgsi01", "D711RGSI01"]


def test_http_endpoint_disabled_by_default(monkeypatch):
    monkeypatch.delenv("TG_HTTP_ENABLED", raising=False)
    assert runner.http_enabled() is False
    monkeypatch.setenv("TG_HTTP_ENABLED", "True")
    assert runner.http_enabled() is True


def test_assignment_name_is_validated_before_query():
    assert "rg-tag-governance-audit" in queries.rg_query("RG-Tag-Governance-Audit")
    for bad in ('x" | take 1 //', "a b", ""):
        with pytest.raises(ValueError):
            queries.vm_query(bad)


def test_queries_avoid_reserved_column_names():
    # Resource Graph ตอบ ParserFailure ถ้า project คอลัมน์ชื่อ kind
    from tag_governance.queries import rg_query, vm_query

    for q in (rg_query("rg-tag-governance-audit"), vm_query("rg-tag-governance-audit")):
        last = q.strip().splitlines()[-1]
        assert " kind =" not in last and " name =" not in last


def test_manual_send_disabled_by_default(monkeypatch):
    monkeypatch.delenv("TG_MANUAL_SEND_ENABLED", raising=False)
    assert runner.manual_send_enabled() is False
    monkeypatch.setenv("TG_MANUAL_SEND_ENABLED", "true")
    assert runner.manual_send_enabled() is True


def test_runner_manual_send_any_day_without_persisting(tmp_path, env):
    st = LocalStore(tmp_path)
    runner.run(today=date(2026, 10, 19), dry_run=False, items=[item("a")], store=st)
    before = st.get("state.json")
    # วันพุธ (ไม่ใช่วันส่ง) ส่งนอกรอบได้ แต่ state/snapshot ต้องไม่เปลี่ยน
    r = runner.run(today=date(2026, 10, 21), dry_run=False, force=True, persist=False, items=[item("a"), item("b")], store=st)
    assert r["status"] == "ok" and len(env) == 2
    assert st.get("state.json") == before and st.get("snapshots/2026-10-21.json") is None


def test_http_json_response_declares_utf8():
    # ไม่มี charset -> Invoke-RestMethod (PowerShell 5.1) อ่านเป็น ISO-8859-1 แล้วภาษาไทยเพี้ยน
    import json

    import function_app

    r = function_app._json_response({"subject": "ค้าง 8 รายการ"})
    assert r.mimetype == "application/json; charset=utf-8"
    assert json.loads(r.get_body().decode("utf-8"))["subject"] == "ค้าง 8 รายการ"
