"""Resource Graph query: Workbook (workbook/tag-governance.workbook.json) ใช้ query ชุดเดียวกันนี้
สร้างไฟล์ Workbook ใหม่ด้วย `python scripts/build_workbook.py` ทุกครั้งที่แก้ไฟล์นี้

ผลลัพธ์ทุกแถว: resource_id, azure_id (id ตัวพิมพ์เดิม), kind, name, rg_name, cause, detail, owner_value, who
  detail = สิ่งที่ไม่ผ่านแยกราย tag เช่น "ไม่มี department, environment ค่าไม่ถูก: prod"
  who    = งานถัดไปของ Cloud team
           "Cloud team แก้ได้" : tag มีค่าแล้วแต่รูปแบบ/ค่าไม่ถูก แก้ได้เลย
           "ถาม owner"         : มี owner แต่ขาด tag อื่น ต้องถามข้อมูลจาก owner
           "หา owner ก่อน"     : ไม่มี owner ที่ติดต่อได้ ต้องหาเจ้าของ resource ก่อน"""
from __future__ import annotations

import re

WHO_FIX = "Cloud team แก้ได้"
WHO_ASK = "ถาม owner"
WHO_FIND = "หา owner ก่อน"

_BASE = """policyresources
| where type == "microsoft.policyinsights/policystates"
| where tolower(tostring(properties.policyAssignmentId)) endswith "/providers/microsoft.authorization/policyassignments/{assignment}"
| where tostring(properties.complianceState) == "NonCompliant"
"""

# policyDefinitionReferenceId ของ initiative ตั้งชื่อเป็น require-tag-<ชื่อ tag> จึงอ่านชื่อ tag จาก ID ได้
_DETAIL = """| extend t = todynamic(tostring(tags))
| extend owner_value = tostring(t.owner)
| mv-expand policy = failed_policies
| extend tag = replace_string(tolower(tostring(policy)), "require-tag-", "")
| extend tag_value = tostring(t[tag])
| extend problem = case(tag == "owner" and owner_value =~ "nan", "owner = nan", tag == "owner" and isempty(tag_value), "ไม่มี owner", tag == "owner", "owner รูปแบบผิด", isempty(tag_value), strcat("ไม่มี ", tag), strcat(tag, " ค่าไม่ถูก: ", tag_value))
| summarize problems = make_list(problem), n_missing = countif(tag != "owner" and isempty(tag_value)), failed_policies = make_set(policy) by resource_id, azure_id, resource_name, rg_name, owner_value, tags_s = tostring(tags)
| extend cause = case(isempty(tags_s) or tags_s == "{{}}", "ไม่มี tag เลย", owner_value =~ "nan", "owner = nan", isempty(owner_value), "ไม่มี owner tag", tostring(failed_policies) contains "owner", "owner รูปแบบผิด", "tag อื่นไม่ครบ")
| extend detail = iff(cause == "ไม่มี tag เลย", "ไม่มี tag เลย", array_strcat(problems, ", "))
| extend who = case(cause in ("ไม่มี tag เลย", "owner = nan", "ไม่มี owner tag"), "{find}", n_missing > 0, "{ask}", "{fix}")
"""


def _check_assignment(assignment: str) -> str:
    """ชื่อ assignment ถูกใส่ลงใน KQL ตรงๆ จึงอนุญาตเฉพาะอักขระที่ Azure ใช้ในชื่อ"""
    if not re.fullmatch(r"[A-Za-z0-9._-]+", assignment or ""):
        raise ValueError("TG_ASSIGNMENT_NAME มีอักขระที่ไม่อนุญาต (ใช้ได้เฉพาะ a-z A-Z 0-9 . _ -)")
    return assignment


def _query(assignment: str, resource_type: str, lookup: str, kind: str) -> str:
    return (
        _BASE.format(assignment=_check_assignment(assignment).lower())
        + f"""| where tostring(properties.resourceType) =~ "{resource_type}"
| extend resource_id = tolower(tostring(properties.resourceId)), policy = tostring(properties.policyDefinitionReferenceId)
| summarize failed_policies = make_set(policy) by resource_id
| join kind=leftouter ({lookup}) on resource_id
"""
        + _DETAIL.format(find=WHO_FIND, ask=WHO_ASK, fix=WHO_FIX)
        + f"""| project resource_id, azure_id, resource_kind = "{kind}", resource_name, rg_name, cause, detail, owner_value, who
"""
    )


def rg_query(assignment: str) -> str:
    return _query(
        assignment,
        "microsoft.resources/subscriptions/resourcegroups",
        'resourcecontainers | where type =~ "microsoft.resources/subscriptions/resourcegroups" | project resource_id = tolower(id), azure_id = id, resource_name = name, rg_name = name, tags',
        "Resource Group",
    )


def vm_query(assignment: str) -> str:
    # คอลัมน์ resourceGroup เป็นตัวพิมพ์เล็กเสมอ จึงอ่านชื่อ RG จาก id แทน ให้ตรงกับที่แสดงใน portal
    return _query(
        assignment,
        "microsoft.compute/virtualmachines",
        'resources | where type =~ "microsoft.compute/virtualmachines" | project resource_id = tolower(id), azure_id = id, resource_name = name, rg_name = tostring(split(id, "/")[4]), tags',
        "Virtual Machine",
    )


def all_query(assignment: str) -> str:
    """RG และ VM รวมในผลลัพธ์เดียว (ใช้ใน Workbook)"""
    return rg_query(assignment) + "| union (\n" + vm_query(assignment) + ")\n"


def fetch_items(credential, assignment: str, subscription_ids: list[str] | None = None) -> list[dict]:
    """ดึงรายการที่ไม่ผ่านจาก Resource Graph (RG + VM)"""
    from azure.mgmt.resourcegraph import ResourceGraphClient
    from azure.mgmt.resourcegraph.models import QueryRequest, QueryRequestOptions

    client = ResourceGraphClient(credential)
    items: list[dict] = []
    for q in (rg_query(assignment), vm_query(assignment)):
        skip_token = None
        while True:
            opts = QueryRequestOptions(result_format="objectArray", top=1000, skip_token=skip_token)
            req = QueryRequest(query=q, options=opts)
            if subscription_ids:
                req.subscriptions = subscription_ids
            res = client.resources(req)
            items.extend(res.data)
            skip_token = res.skip_token
            if not skip_token:
                break
    for it in items:
        # Resource Graph ไม่ยอมให้ตั้งชื่อคอลัมน์ว่า kind (ParserFailure) จึงใช้ resource_kind / resource_name ใน query แล้วแปลงกลับตรงนี้
        it["kind"] = it.pop("resource_kind", None) or it.get("kind") or ""
        it["name"] = it.pop("resource_name", None) or it.get("name") or ""
        it["resource_id"] = (it.get("resource_id") or "").lower()
        for k in ("name", "rg_name", "cause", "detail", "owner_value", "who"):
            it[k] = it.get(k) or ""
    return items


def filter_scope(items: list[dict], rg_regex: str = "") -> list[dict]:
    """กรองเหลือเฉพาะ RG ที่ชื่อตรงรูปแบบ (เว้นว่าง = ไม่กรอง) เช่น VM ใน managed RG ของ Databricks จะถูกตัดออก"""
    import re

    if not rg_regex.strip():
        return items
    rx = re.compile(rg_regex, re.IGNORECASE)
    return [i for i in items if rx.search(i.get("rg_name") or "")]
