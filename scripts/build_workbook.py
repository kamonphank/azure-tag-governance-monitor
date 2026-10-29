"""สร้าง workbook/tag-governance.workbook.json จาก query ใน function/tag_governance/queries.py
ให้ Workbook กับอีเมลใช้ตรรกะเดียวกันเสมอ

    python scripts/build_workbook.py          # เขียนไฟล์ใหม่
    python scripts/build_workbook.py --check  # แค่ตรวจว่าไฟล์ตรงกับ query ล่าสุด (ใช้ใน test)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "function"))

from tag_governance.queries import CHANGE_TABLES, SUBSCRIPTION_ID, WHO_ASK, WHO_FIND, WHO_FIX, WHO_PENDING, all_query, changes_query  # noqa: E402

ASSIGNMENT = "rg-tag-governance-audit"
OUT = ROOT / "workbook" / "tag-governance.workbook.json"

# สีเดียวกับป้ายในอีเมล (core.py)
WHO_COLORS = [(WHO_FIX, "green"), (WHO_ASK, "orange"), (WHO_FIND, "redBright")]
WHO_ORDER = f'case(who == "{WHO_FIX}", 1, who == "{WHO_ASK}", 2, who == "{WHO_FIND}", 3, 4)'
KIND_RG = 'resource_kind == "Resource Group"'
KIND_VM = 'resource_kind == "Virtual Machine"'
RG_NAME_PATTERN = r"^[DTP][0-9]{3}RG[A-Z]{2}[0-9]{2}$"


def _arg(query: str, title: str = "", resource_type: str = "microsoft.resourcegraph/resources", **extra) -> dict:
    content = {
        "version": "KqlItem/1.0",
        "query": query,
        "queryType": 1,
        "resourceType": resource_type,
        "crossComponentResources": [f"/subscriptions/{SUBSCRIPTION_ID}"],
    }
    if title:
        content["title"] = title
    content.update(extra)
    return content


def _text(name: str, md: str) -> dict:
    return {"type": 1, "content": {"json": md}, "name": name}


def _who_formatter(column: str) -> dict:
    grid = [{"operator": "==", "thresholdValue": w, "representation": c, "text": "{0}{1}"} for w, c in WHO_COLORS]
    grid.append({"operator": "Default", "thresholdValue": None, "representation": "gray", "text": "{0}{1}"})
    return {"columnMatch": column, "formatter": 18, "formatOptions": {"thresholdsOptions": "colors", "thresholdsGrid": grid}}


def _hidden(column: str) -> dict:
    return {"columnMatch": column, "formatter": 5}


def _width(column: str, width: str, formatter: int = 0) -> dict:
    return {"columnMatch": column, "formatter": formatter, "formatOptions": {"customColumnWidthSetting": width}}


def _highlight_width(column: str, width: str, color: str = "yellow") -> dict:
    return {
        "columnMatch": column,
        "formatter": 18,
        "formatOptions": {
            "customColumnWidthSetting": width,
            "thresholdsOptions": "colors",
            "thresholdsGrid": [
                {"operator": "Default", "thresholdValue": None, "representation": color, "text": "{0}{1}"}
            ],
        },
    }


def _changes_param(name: str, table: str) -> dict:
    query = (
        changes_query(table)
        + "| summarize pairs = make_list(strcat('\"', resource_id, '\":\"', tostring(tags_changed_at), '\"'))\n"
        + '| project value = strcat("{", array_strcat(pairs, ","), "}")'
    )
    return {
        "id": f"tg-{name.lower()}",
        "version": "KqlParameterItem/1.0",
        "name": name,
        "type": 1,
        "query": query,
        "crossComponentResources": [f"/subscriptions/{SUBSCRIPTION_ID}"],
        "isHiddenWhenLocked": True,
        "queryType": 1,
        "resourceType": "microsoft.resourcegraph/resources",
    }


def build() -> dict:
    # ตารางประวัติการเปลี่ยนแปลง join กับตารางอื่นไม่ได้ จึงให้ parameter ที่ซ่อนไว้ query แยก
    # แล้วส่งผลเป็น JSON {resource_id: เวลาที่แก้ tag ล่าสุด} เข้ามาใน query หลัก (ตรรกะเดียวกับ queries.mark_pending)
    base = (
        all_query(ASSIGNMENT)
        + "| extend rg_changed = tostring(todynamic('{ChangedRG}')[resource_id]), vm_changed = tostring(todynamic('{ChangedVM}')[resource_id])\n"
        + "| extend tags_changed_at = todatetime(iff(isnotempty(rg_changed), rg_changed, vm_changed))\n"
        + f'| extend who = iff(isnotnull(tags_changed_at) and tags_changed_at > evaluated_at, "{WHO_PENDING}", who)\n'
    )

    tiles = [
        ("ไม่ผ่านทั้งหมด", f'who != "{WHO_PENDING}"'),  # รายการที่รอ Policy ตรวจซ้ำไม่นับรวม
        (WHO_FIX, f'who == "{WHO_FIX}"'),
        (WHO_ASK, f'who == "{WHO_ASK}"'),
        (WHO_FIND, f'who == "{WHO_FIND}"'),
    ]

    def _counts(i: int, c: str) -> str:
        return f"n{i} = countif({c}), rg{i} = countif({c} and {KIND_RG}), vm{i} = countif({c} and {KIND_VM})"

    counts = ", ".join(_counts(i, c) for i, (_, c) in enumerate(tiles))
    packs = ", ".join(f'pack("ord", {i}, "k", "{t}", "n", n{i}, "sub", strcat("RG ", rg{i}, "  ·  VM ", vm{i}))' for i, (t, _) in enumerate(tiles))
    tiles_q = (
        base
        + f"| summarize {counts}\n"
        + f"| extend p = pack_array({packs})\n"
        + "| mv-expand p\n| project ord = toint(p.ord), title = tostring(p.k), n = toint(p.n), sub = tostring(p.sub)\n| order by ord asc"
    )

    items_q = (
        base
        + '| where "*" in ({Action}) or who in ({Action})\n'
        + f'| where "*" in ({{Kind}}) or resource_kind in ({{Kind}})\n'
        + f'| extend who_order = {WHO_ORDER}, rg_col = iff({KIND_RG}, "", rg_name)\n'
        + "| order by who_order asc, resource_kind asc, resource_name asc\n"
        + "| project azure_id, resource_kind, rg_col, who, detail, owner_value, evaluated_at"
    )

    # Azure Policy compliance ไม่ได้ช่วยหา key ที่ตัวพิมพ์ต่างจากมาตรฐานในบางกรณี
    # ตรวจ tag ปัจจุบันจาก Resource Graph โดยตรง เพื่อให้พบ resource ที่ Policy มองว่าผ่านด้วย
    casing_q = '''resourcecontainers
| where type =~ "microsoft.resources/subscriptions/resourcegroups"
    | where subscriptionId == "{SUBSCRIPTION_ID}"
    | where toupper(name) matches regex @"{RG_NAME_PATTERN}"
    | project azure_id = id, resource_name = name, rg_name = name, resource_kind = "Resource Group", tags
    | union (resources
    | where type =~ "microsoft.compute/virtualmachines"
    | where subscriptionId == "{SUBSCRIPTION_ID}"
    | where toupper(tostring(split(id, "/")[4])) matches regex @"{RG_NAME_PATTERN}"
    | project azure_id = id, resource_name = name, rg_name = tostring(split(id, "/")[4]), resource_kind = "Virtual Machine", tags)
| extend tag_bag = todynamic(tags)
| mv-expand tag_key = bag_keys(tag_bag)
| extend tag_key = tostring(tag_key), expected_key = tolower(tostring(tag_key))
| where expected_key in ("owner", "department", "environment", "project") and tag_key != expected_key
| extend tag_value = tostring(tag_bag[tag_key])
| extend rg_col = iff(resource_kind == "Resource Group", "", rg_name)
| order by resource_kind asc, resource_name asc, expected_key asc
| project azure_id, resource_kind, rg_col, resource_name, tag_key, expected_key, tag_value'''.replace(
        "{SUBSCRIPTION_ID}", SUBSCRIPTION_ID
    ).replace("{RG_NAME_PATTERN}", RG_NAME_PATTERN)

    def static_param(name: str, label: str, values: list[str]) -> dict:
        return {
            "id": f"tg-{name.lower()}",
            "version": "KqlParameterItem/1.0",
            "name": name,
            "label": label,
            "type": 2,
            "multiSelect": True,
            "quote": "'",
            "delimiter": ",",
            "typeSettings": {"additionalResourceOptions": ["value::all"], "showDefault": False, "selectAllValue": "*"},
            "jsonData": json.dumps([{"value": v, "label": v} for v in values], ensure_ascii=False),
            "defaultValue": "value::all",
        }

    return {
        "version": "Notebook/1.0",
        "items": [
            _text(
                "text - title",
                "# Tag Governance\n"
                f"Resource Group และ VM ที่ยังไม่ผ่าน policy `{ASSIGNMENT}` · ดึงสดจาก Azure Policy ทุกครั้งที่เปิด · "
                f"รายการที่เพิ่งแก้ tag จะขึ้นว่า **{WHO_PENDING}** จนกว่า Policy จะตรวจใหม่",
            ),
            {
                "type": 9,
                "content": {
                    "version": "KqlParameterItem/1.0",
                    "parameters": [_changes_param(name, table) for name, table in zip(("ChangedRG", "ChangedVM"), CHANGE_TABLES)],
                    "style": "pills",
                    "queryType": 1,
                    "resourceType": "microsoft.resourcegraph/resources",
                },
                "name": "parameters - changes (hidden)",
            },
            {
                "type": 3,
                "content": _arg(
                    tiles_q,
                    size=3,
                    visualization="tiles",
                    tileSettings={
                        "showBorder": True,
                        "titleContent": _who_formatter("title"),
                        "leftContent": {
                            "columnMatch": "n",
                            "formatter": 1,
                            "numberFormat": {"unit": 17, "options": {"maximumFractionDigits": 0}},
                        },
                        "secondaryContent": {"columnMatch": "sub", "formatter": 1},
                    },
                ),
                "name": "query - tiles",
            },
            _text(
                "text - legend",
                f"**{WHO_FIX}** - tag มีค่าแล้วแต่รูปแบบหรือค่าไม่ถูก แก้ได้เลย  \n"
                f"**{WHO_ASK}** - มี owner แต่ขาด tag อื่น ติดต่อ owner เพื่อขอข้อมูล  \n"
                f"**{WHO_FIND}** - ไม่มี owner ที่ติดต่อได้ ต้องหาเจ้าของ resource ก่อน  \n"
                f"**{WHO_PENDING}** - แก้ tag แล้วหลังจาก Policy ตรวจรอบล่าสุด รอผลยืนยัน (ปกติภายใน 30 นาที) ไม่ต้องทำอะไร "
                "และไม่นับรวมในตัวเลขด้านบน · ถ้าค้างนาน สั่งตรวจทันทีด้วย `az policy state trigger-scan --resource-group <ชื่อ RG>`",
            ),
            _text("text - items", "## รายการที่ไม่ผ่าน"),
            {
                "type": 9,
                "content": {
                    "version": "KqlParameterItem/1.0",
                    "parameters": [
                        static_param("Action", "ต้องทำ", [WHO_FIX, WHO_ASK, WHO_FIND, WHO_PENDING]),
                        static_param("Kind", "ประเภท", ["Resource Group", "Virtual Machine"]),
                    ],
                    "style": "pills",
                    "queryType": 0,
                },
                "name": "parameters - filter",
            },
            {
                "type": 3,
                "content": _arg(
                    items_q,
                    size=3,
                    visualization="table",
                    showExportToExcel=True,
                    exportToExcelOptions="visible",
                    noDataMessage="ไม่มีรายการที่ไม่ผ่าน",
                    gridSettings={
                        "rowLimit": 1000,
                        "filter": True,
                        "formatters": [
                            {"columnMatch": "azure_id", "formatter": 13, "formatOptions": {"linkTarget": "Resource", "showIcon": False, "customColumnWidthSetting": "20ch"}},
                            _width("resource_kind", "15ch"),
                            _width("rg_col", "15ch"),
                            {**_who_formatter("who"), "formatOptions": {**_who_formatter("who")["formatOptions"], "customColumnWidthSetting": "18ch"}},
                            _width("detail", "70ch"),
                            _width("owner_value", "40ch"),
                        ],
                        "labelSettings": [
                            {"columnId": "azure_id", "label": "ชื่อ"},
                            {"columnId": "resource_kind", "label": "ประเภท"},
                            {"columnId": "rg_col", "label": "อยู่ใน RG"},
                            {"columnId": "who", "label": "ต้องทำ"},
                            {"columnId": "detail", "label": "สิ่งที่ไม่ผ่าน"},
                            {"columnId": "owner_value", "label": "ค่า owner ที่มี"},
                            {"columnId": "evaluated_at", "label": "Policy ตรวจล่าสุด"},
                        ],
                    },
                ),
                "name": "query - items",
            },
            _text(
                "text - casing",
                "## Tag key ที่ตัวพิมพ์ไม่ตรงมาตรฐาน\n"
                "ตรวจจาก tag ปัจจุบันโดยตรงเฉพาะ RG และ VM ใน RG ที่ชื่อเป็นรูปแบบ "
                "`D###RG??##`, `T###RG??##` หรือ `P###RG??##` รวม resource ที่ Azure Policy อาจรายงานว่าผ่าน "
                "ให้แก้ key เป็นตัวพิมพ์เล็กตามมาตรฐาน เช่น `Owner` → `owner`",
            ),
            {
                "type": 3,
                "content": _arg(
                    casing_q,
                    size=3,
                    visualization="table",
                    showExportToExcel=True,
                    exportToExcelOptions="visible",
                    noDataMessage="ไม่พบ tag key ที่ตัวพิมพ์ไม่ตรงมาตรฐาน",
                    gridSettings={
                        "rowLimit": 1000,
                        "filter": True,
                        "formatters": [
                            {"columnMatch": "azure_id", "formatter": 13, "formatOptions": {"linkTarget": "Resource", "showIcon": False, "customColumnWidthSetting": "20ch"}},
                            _width("resource_kind", "15ch"),
                            _width("rg_col", "15ch"),
                            _width("resource_name", "30ch"),
                            _highlight_width("tag_key", "20ch"),
                            _width("expected_key", "20ch"),
                            _width("tag_value", "35ch"),
                        ],
                        "labelSettings": [
                            {"columnId": "azure_id", "label": "ชื่อ resource"},
                            {"columnId": "resource_kind", "label": "ประเภท"},
                            {"columnId": "rg_col", "label": "อยู่ใน RG"},
                            {"columnId": "resource_name", "label": "ชื่อ"},
                            {"columnId": "tag_key", "label": "key ที่พบ"},
                            {"columnId": "expected_key", "label": "key มาตรฐาน"},
                            {"columnId": "tag_value", "label": "ค่า tag"},
                        ],
                    },
                ),
                "name": "query - casing",
            },
        ],
        "$schema": "https://github.com/Microsoft/Application-Insights-Workbooks/blob/master/schema/workbook.json",
    }


def render() -> str:
    return json.dumps(build(), ensure_ascii=False, indent=2) + "\n"


if __name__ == "__main__":
    text = render()
    if "--check" in sys.argv:
        if OUT.read_text(encoding="utf-8") != text:
            sys.exit(f"{OUT.relative_to(ROOT)} ไม่ตรงกับ queries.py ให้รัน python scripts/build_workbook.py")
        print("ok")
    else:
        OUT.write_text(text, encoding="utf-8")
        print(f"เขียน {OUT.relative_to(ROOT)} แล้ว")
