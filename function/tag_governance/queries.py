"""Resource Graph query: Workbook (workbook/tag-governance.workbook.json) ใช้ query ชุดเดียวกันนี้
สร้างไฟล์ Workbook ใหม่ด้วย `python scripts/build_workbook.py` ทุกครั้งที่แก้ไฟล์นี้

ผลลัพธ์ทุกแถว: resource_id, azure_id (id ตัวพิมพ์เดิม), kind, name, rg_name, cause, detail, owner_value, who, evaluated_at
  evaluated_at = เวลาที่ Policy ประเมินล่าสุด (UTC) ถ้าแก้ tag หลังเวลานี้ แปลว่ารอ Policy ประเมินใหม่
  detail = สิ่งที่ไม่ผ่านแยกราย tag เช่น "ไม่มี department, environment ค่าไม่ถูก: prod"
  who    = งานถัดไปของ Cloud team
           "Cloud team แก้ได้" : tag มีค่าแล้วแต่รูปแบบ/ค่าไม่ถูก แก้ได้เลย
           "ถาม owner"         : มี owner แต่ขาด tag อื่น ต้องถามข้อมูลจาก owner
           "หา owner ก่อน"     : ไม่มี owner ที่ติดต่อได้ ต้องหาเจ้าของ resource ก่อน
           "รอ Policy ตรวจซ้ำ" : tag ถูกแก้หลังเวลาที่ Policy ตรวจล่าสุด รอผลยืนยัน ไม่ต้องทำอะไร
                                 (ไม่นับรวมในตัวเลข ไม่ escalate ไม่อยู่ในรายชื่อ owner)"""
from __future__ import annotations

import re
from datetime import datetime, timezone

WHO_FIX = "Cloud team แก้ได้"
WHO_ASK = "ถาม owner"
WHO_FIND = "หา owner ก่อน"
WHO_PENDING = "รอ Policy ตรวจซ้ำ"
SUBSCRIPTION_ID = "__DEPLOYMENT_SUBSCRIPTION_ID__"

_BASE = """policyresources
| where type == "microsoft.policyinsights/policystates"
| where subscriptionId == "{subscription_id}"
| where tolower(tostring(properties.policyAssignmentId)) endswith "/providers/microsoft.authorization/policyassignments/{assignment}"
| where tostring(properties.complianceState) == "NonCompliant"
"""

# เรียงสิ่งที่ไม่ผ่าน: owner ก่อน แล้ว tag ที่ไม่มี แล้ว tag ที่ค่าไม่ถูก
# policyDefinitionReferenceId ของ initiative ตั้งชื่อเป็น require-tag-<ชื่อ tag> จึงอ่านชื่อ tag จาก ID ได้
_DETAIL = """| extend t = todynamic(tostring(tags))
| extend owner_value = tostring(t.owner)
| mv-expand policy = failed_policies
| extend tag = replace_string(tolower(tostring(policy)), "require-tag-", "")
| extend tag_value = tostring(t[tag])
| extend problem = case(
    tag == "owner" and owner_value =~ "nan", "owner = nan",
    isempty(tag_value), strcat("ไม่มี ", tag),
    tag == "owner" and tag_value contains " ", "owner มีช่องว่าง (คั่นหลายอีเมลด้วย comma)",
    tag == "owner" and tag_value contains "\\t", "owner มี tab",
    tag == "owner" and tag_value contains "\\r", "owner มี carriage return",
    tag == "owner" and tag_value contains "\\n", "owner มีขึ้นบรรทัดใหม่",
    tag == "owner" and (tag_value contains ",," or tag_value startswith "," or tag_value endswith ","), "owner คั่นอีเมลด้วย comma ไม่ถูกต้อง",
    tag == "owner" and array_length(split(tag_value, ",")) > 100, "owner มีอีเมลเกิน 100 รายการ",
    tag == "owner" and not(tag_value matches regex @"^[^,@\\s]+@[^,@\\s]+(,[^,@\\s]+@[^,@\\s]+)*$"), "owner รูปแบบอีเมลไม่ถูกต้อง",
    tag == "owner", "owner domain ไม่ตรงกับ Policy (ต้องตรงตามค่าที่กำหนดและเป็นตัวพิมพ์เล็ก)",
    tag == "department" and (tag_value contains "\\r" or tag_value contains "\\n"), "department มีอักขระขึ้นบรรทัดใหม่",
    tag == "department", strcat("department ไม่อยู่ในค่าที่ Policy อนุญาต: ", tag_value),
    tag == "environment" and (tag_value contains "\\r" or tag_value contains "\\n"), "environment มีอักขระขึ้นบรรทัดใหม่",
    tag == "environment", strcat("environment ไม่อยู่ในค่าที่ Policy อนุญาต: ", tag_value),
    tag == "project" and tag_value contains "\\t", "project มี tab",
    tag == "project" and (tag_value contains "\\r" or tag_value contains "\\n"), "project มีอักขระขึ้นบรรทัดใหม่",
    tag == "project" and tag_value contains ",,", "project มี comma ซ้ำ",
    tag == "project" and (tag_value startswith "," or tag_value endswith ","), "project มี comma นำหน้าหรือต่อท้าย",
    tag == "project" and tag_value contains ", ", "project มีช่องว่างหลัง comma",
    tag == "project" and tag_value contains " ,", "project มีช่องว่างก่อน comma",
    tag == "project", strcat("project ไม่ผ่านรูปแบบที่ Policy กำหนด: ", tag_value),
    strcat(tag, " ค่าไม่ถูก: ", tag_value))
| extend rank = case(tag == "owner", 0, isempty(tag_value), 1, 2)
| order by resource_id asc, rank asc, tag asc
| summarize problems = make_list(problem), n_missing = countif(tag != "owner" and isempty(tag_value)), failed_policies = make_set(policy) by resource_id, azure_id, resource_name, rg_name, owner_value, evaluated_at, tags_s = tostring(tags)
| extend cause = case(isempty(tags_s) or tags_s == "{{}}", "ไม่มี tag เลย", owner_value =~ "nan", "owner = nan", isempty(owner_value), "ไม่มี owner tag", tostring(failed_policies) contains "owner", "owner รูปแบบผิด", "tag อื่นไม่ครบ")
| extend detail = iff(cause == "ไม่มี tag เลย", "ไม่มี tag เลย", array_strcat(problems, ", "))
| extend who = case(cause in ("ไม่มี tag เลย", "owner = nan", "ไม่มี owner tag"), "{find}", n_missing > 0, "{ask}", "{fix}")
"""


def _check_assignment(assignment: str) -> str:
    """ชื่อ assignment ถูกใส่ลงใน KQL ตรงๆ จึงอนุญาตเฉพาะอักขระที่ Azure ใช้ในชื่อ"""
    if not re.fullmatch(r"[A-Za-z0-9._-]+", assignment or ""):
        raise ValueError("TG_ASSIGNMENT_NAME มีอักขระที่ไม่อนุญาต (ใช้ได้เฉพาะ a-z A-Z 0-9 . _ -)")
    return assignment


_COLS = "resource_id, azure_id, resource_kind, resource_name, rg_name, cause, detail, owner_value, who, evaluated_at"


def _body(assignment: str, resource_type: str, lookup: str, kind: str) -> str:
    return (
        _BASE.format(assignment=_check_assignment(assignment).lower(), subscription_id=SUBSCRIPTION_ID)
        + f"""| where tostring(properties.resourceType) =~ "{resource_type}"
| extend resource_id = tolower(tostring(properties.resourceId)), policy = tostring(properties.policyDefinitionReferenceId)
| summarize failed_policies = make_set(policy), evaluated_at = max(todatetime(properties.timestamp)) by resource_id
| join kind=leftouter ({lookup}) on resource_id
"""
        + _DETAIL.format(find=WHO_FIND, ask=WHO_ASK, fix=WHO_FIX)
        + f"""| extend resource_kind = "{kind}"
| project {_COLS}
"""
    )


# ค่า tag อ่านสด แต่ผ่าน/ไม่ผ่านมาจากรอบที่ Policy ตรวจล่าสุด ถ้า tag ถูกแก้หลังรอบนั้น ถือว่ารอ Policy ตรวจซ้ำ
# (ไม่ใช่งานที่ต้องทำ) ดูเวลาที่แก้จากประวัติการเปลี่ยนแปลงของ Resource Graph ซึ่งเก็บราว 14 วัน
# ตารางประวัติ join/union กับตารางอื่นไม่ได้ จึงต้อง query แยก แล้วนำผลมาเทียบทีหลัง
# (Function เทียบใน Python ด้วย mark_pending, Workbook ส่งผลผ่าน parameter ที่ซ่อนไว้)
CHANGE_TABLES = ("resourcecontainerchanges", "resourcechanges")  # RG, VM


def changes_query(table: str) -> str:
    if table not in CHANGE_TABLES:
        raise ValueError(table)
    return f"""{table}
| where subscriptionId == "{SUBSCRIPTION_ID}"
| where tostring(properties.changes) contains "tags"
| summarize tags_changed_at = max(todatetime(properties.changeAttributes.timestamp)) by resource_id = tolower(tostring(properties.targetResourceId))
"""


def _parse_time(v):
    try:
        t = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def mark_pending(items: list[dict], tags_changed_at: dict[str, str]) -> list[dict]:
    """เปลี่ยน who เป็น WHO_PENDING ให้รายการที่ tag ถูกแก้หลังเวลาที่ Policy ตรวจล่าสุด"""
    for it in items:
        changed = _parse_time(tags_changed_at.get(it["resource_id"]) or "")
        evaluated = _parse_time(it.get("evaluated_at") or "")
        if changed and evaluated and changed > evaluated:
            it["who"] = WHO_PENDING
    return items


def rg_query(assignment: str) -> str:
    return _body(
        assignment,
        "microsoft.resources/subscriptions/resourcegroups",
        f'resourcecontainers | where subscriptionId == "{SUBSCRIPTION_ID}" | where type =~ "microsoft.resources/subscriptions/resourcegroups" | project resource_id = tolower(id), azure_id = id, resource_name = name, rg_name = name, tags',
        "Resource Group",
    )


def vm_query(assignment: str) -> str:
    # คอลัมน์ resourceGroup เป็นตัวพิมพ์เล็กเสมอ จึงอ่านชื่อ RG จาก id แทน ให้ตรงกับที่แสดงใน portal
    return _body(
        assignment,
        "microsoft.compute/virtualmachines",
        f'resources | where subscriptionId == "{SUBSCRIPTION_ID}" | where type =~ "microsoft.compute/virtualmachines" | project resource_id = tolower(id), azure_id = id, resource_name = name, rg_name = tostring(split(id, "/")[4]), tags',
        "Virtual Machine",
    )


def all_query(assignment: str) -> str:
    """RG และ VM รวมในผลลัพธ์เดียว (ใช้ใน Workbook)"""
    return rg_query(assignment) + "| union (\n" + vm_query(assignment) + ")\n"


def _run(client, query: str, subscription_ids: list[str] | None) -> list[dict]:
    from azure.mgmt.resourcegraph.models import QueryRequest, QueryRequestOptions

    rows: list[dict] = []
    skip_token = None
    while True:
        opts = QueryRequestOptions(result_format="objectArray", top=1000, skip_token=skip_token)
        req = QueryRequest(query=query, options=opts)
        if subscription_ids:
            req.subscriptions = subscription_ids
        res = client.resources(req)
        rows.extend(res.data)
        skip_token = res.skip_token
        if not skip_token:
            return rows


def fetch_items(credential, assignment: str, subscription_ids: list[str] | None = None) -> list[dict]:
    """ดึงรายการที่ไม่ผ่านจาก Resource Graph (RG + VM) แล้วแยกรายการที่รอ Policy ตรวจซ้ำ"""
    import logging

    from azure.mgmt.resourcegraph import ResourceGraphClient

    client = ResourceGraphClient(credential)
    items: list[dict] = []
    for q in (rg_query(assignment), vm_query(assignment)):
        items.extend(_run(client, q, subscription_ids))
    for it in items:
        # Resource Graph ไม่ยอมให้ตั้งชื่อคอลัมน์ว่า kind (ParserFailure) จึงใช้ resource_kind / resource_name ใน query แล้วแปลงกลับตรงนี้
        it["kind"] = it.pop("resource_kind", None) or it.get("kind") or ""
        it["name"] = it.pop("resource_name", None) or it.get("name") or ""
        it["resource_id"] = (it.get("resource_id") or "").lower()
        for k in ("name", "rg_name", "cause", "detail", "owner_value", "who", "evaluated_at"):
            it[k] = str(it.get(k) or "")
    changed: dict[str, str] = {}
    for table in CHANGE_TABLES:
        try:
            for r in _run(client, changes_query(table), subscription_ids):
                changed[(r.get("resource_id") or "").lower()] = str(r.get("tags_changed_at") or "")
        except Exception:  # noqa: BLE001 อ่านประวัติไม่ได้ก็ยังส่งรายงานได้ แค่ไม่แยกรายการที่รอตรวจซ้ำ
            logging.exception("อ่าน %s ไม่สำเร็จ ข้ามการแยกรายการที่รอ Policy ตรวจซ้ำ", table)
    return mark_pending(items, changed)


def filter_scope(items: list[dict], rg_regex: str = "") -> list[dict]:
    """กรองเหลือเฉพาะ RG ที่ชื่อตรงรูปแบบ (เว้นว่าง = ไม่กรอง) เช่น VM ใน managed RG ของ Databricks จะถูกตัดออก"""
    import re

    if not rg_regex.strip():
        return items
    rx = re.compile(rg_regex, re.IGNORECASE)
    return [i for i in items if rx.search(i.get("rg_name") or "")]
