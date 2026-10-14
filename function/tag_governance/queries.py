"""Resource Graph query: ใช้ตรรกะเดียวกับ Workbook (workbook/tag-governance.workbook.json)
ผลลัพธ์ทุกแถว: resource_id, kind, name, rg_name, cause, owner_value, who"""
from __future__ import annotations

import re

_BASE = """policyresources
| where type == "microsoft.policyinsights/policystates"
| where tolower(tostring(properties.policyAssignmentId)) endswith "/providers/microsoft.authorization/policyassignments/{assignment}"
| where tostring(properties.complianceState) == "NonCompliant"
"""

_CAUSE_RG = """| extend cause = case(isempty(tostring({tags})) or tostring({tags}) == "{{}}", "ไม่มี tag เลย", owner_value =~ "nan", "owner = nan", isempty(owner_value), "ไม่มี owner tag", tostring(failed_policies) contains "owner", "owner รูปแบบผิด", "tag อื่นไม่ครบ")
| extend who = case(cause == "owner รูปแบบผิด" or cause == "tag อื่นไม่ครบ", "Cloud team แก้ได้", "ต้องหา owner / ยืนยัน")
"""


def _check_assignment(assignment: str) -> str:
    """ชื่อ assignment ถูกใส่ลงใน KQL ตรงๆ จึงอนุญาตเฉพาะอักขระที่ Azure ใช้ในชื่อ"""
    if not re.fullmatch(r"[A-Za-z0-9._-]+", assignment or ""):
        raise ValueError("TG_ASSIGNMENT_NAME มีอักขระที่ไม่อนุญาต (ใช้ได้เฉพาะ a-z A-Z 0-9 . _ -)")
    return assignment


def rg_query(assignment: str) -> str:
    return (
        _BASE.format(assignment=_check_assignment(assignment).lower())
        + """| where tostring(properties.resourceType) =~ "microsoft.resources/subscriptions/resourcegroups"
| extend resource_id = tolower(tostring(properties.resourceId)), policy = tostring(properties.policyDefinitionReferenceId)
| summarize failed_policies = make_set(policy) by resource_id
| join kind=leftouter (resourcecontainers | where type =~ "microsoft.resources/subscriptions/resourcegroups" | project resource_id = tolower(id), rg_name = name, rg_tags = tags) on resource_id
| extend t = todynamic(tostring(rg_tags))
| extend owner_value = tostring(t.owner)
"""
        + _CAUSE_RG.format(tags="rg_tags")
        + """| project resource_id, kind = "Resource Group", name = rg_name, rg_name, cause, owner_value, who
"""
    )


def vm_query(assignment: str) -> str:
    return (
        _BASE.format(assignment=_check_assignment(assignment).lower())
        + """| where tostring(properties.resourceType) =~ "microsoft.compute/virtualmachines"
| extend resource_id = tolower(tostring(properties.resourceId)), policy = tostring(properties.policyDefinitionReferenceId)
| summarize failed_policies = make_set(policy) by resource_id
| join kind=leftouter (resources | where type =~ "microsoft.compute/virtualmachines" | project resource_id = tolower(id), vm_name = name, rg_name = resourceGroup, vm_tags = tags) on resource_id
| extend t = todynamic(tostring(vm_tags))
| extend owner_value = tostring(t.owner)
"""
        + _CAUSE_RG.format(tags="vm_tags")
        + """| project resource_id, kind = "Virtual Machine", name = vm_name, rg_name, cause, owner_value, who
"""
    )


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
        it["resource_id"] = (it.get("resource_id") or "").lower()
        for k in ("name", "rg_name", "cause", "owner_value", "who"):
            it[k] = it.get(k) or ""
    return items


def filter_scope(items: list[dict], rg_regex: str = "") -> list[dict]:
    """กรองเหลือเฉพาะ RG ที่ชื่อตรงรูปแบบ (เว้นว่าง = ไม่กรอง) เช่น VM ใน managed RG ของ Databricks จะถูกตัดออก"""
    import re

    if not rg_regex.strip():
        return items
    rx = re.compile(rg_regex, re.IGNORECASE)
    return [i for i in items if rx.search(i.get("rg_name") or "")]
