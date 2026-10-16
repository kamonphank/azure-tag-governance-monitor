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

from tag_governance.queries import WHO_ASK, WHO_FIND, WHO_FIX, all_query  # noqa: E402

ASSIGNMENT = "rg-tag-governance-audit"
OUT = ROOT / "workbook" / "tag-governance.workbook.json"

# สีเดียวกับป้ายในอีเมล (core.py)
WHO_COLORS = [(WHO_FIX, "green"), (WHO_ASK, "orange"), (WHO_FIND, "redBright")]
WHO_ORDER = f'case(who == "{WHO_FIX}", 1, who == "{WHO_ASK}", 2, 3)'
KIND_RG = 'resource_kind == "Resource Group"'
KIND_VM = 'resource_kind == "Virtual Machine"'


def _arg(query: str, title: str = "", **extra) -> dict:
    content = {
        "version": "KqlItem/1.0",
        "query": query,
        "queryType": 1,
        "resourceType": "microsoft.resourcegraph/resources",
        "crossComponentResources": ["{Subscription}"],
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


def build() -> dict:
    base = all_query(ASSIGNMENT)

    tiles = [
        ("ไม่ผ่านทั้งหมด", ""),
        (WHO_FIX, f'who == "{WHO_FIX}"'),
        (WHO_ASK, f'who == "{WHO_ASK}"'),
        (WHO_FIND, f'who == "{WHO_FIND}"'),
    ]

    def _counts(i: int, c: str) -> str:
        if not c:  # Resource Graph ไม่รับ countif(true) จึงใช้ count() กับช่องรวม
            return f"n{i} = count(), rg{i} = countif({KIND_RG}), vm{i} = countif({KIND_VM})"
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
        + "| project azure_id, resource_kind, rg_col, who, detail, owner_value"
    )

    owners_q = (
        base
        + '| extend entry = strcat(iff(' + KIND_RG + ', "RG ", "VM "), resource_name, " (", detail, ")")\n'
        + '| mv-expand owner = split(owner_value, ",")\n'
        + '| extend owner = trim(@"\\s+", tostring(owner))\n'
        + '| where owner != "" and owner !~ "nan"\n'
        + "| summarize n = dcount(resource_id), entries = make_set(entry) by owner\n"
        + '| extend email_ok = iff(owner matches regex @"^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$", "ใช่", "ไม่ใช่ (ตรวจ tag)")\n'
        + '| extend ok_order = iff(email_ok == "ใช่", 1, 0)\n'
        + '| order by ok_order asc, n desc, owner asc\n'
        + '| project owner, email_ok, n, entries = array_strcat(entries, "  ·  ")'
    )

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
                "ผลอัปเดตช้าราว 1 วันหลังแก้ tag",
            ),
            {
                "type": 9,
                "content": {
                    "version": "KqlParameterItem/1.0",
                    "parameters": [
                        {
                            "id": "00ffa1ff-37ea-4cc9-b053-f651df60248d",
                            "version": "KqlParameterItem/1.0",
                            "name": "Subscription",
                            "label": "Subscription",
                            "type": 6,
                            "isRequired": True,
                            "multiSelect": True,
                            "quote": "'",
                            "delimiter": ",",
                            "typeSettings": {"additionalResourceOptions": ["value::all"], "includeAll": True},
                            "timeContext": {"durationMs": 86400000},
                            "defaultValue": "value::all",
                        }
                    ],
                    "style": "pills",
                    "queryType": 0,
                    "resourceType": "microsoft.resourcegraph/resources",
                },
                "name": "parameters - sub",
            },
            {
                "type": 3,
                "content": _arg(
                    tiles_q,
                    size=4,
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
                f"**{WHO_FIX}** — tag มีค่าแล้วแต่รูปแบบหรือค่าไม่ถูก แก้ได้เลย  \n"
                f"**{WHO_ASK}** — มี owner แต่ขาด tag อื่น ติดต่อ owner เพื่อขอข้อมูล  \n"
                f"**{WHO_FIND}** — ไม่มี owner ที่ติดต่อได้ ต้องหาเจ้าของ resource ก่อน",
            ),
            _text("text - items", "## รายการที่ไม่ผ่าน"),
            {
                "type": 9,
                "content": {
                    "version": "KqlParameterItem/1.0",
                    "parameters": [
                        static_param("Action", "ต้องทำ", [WHO_FIX, WHO_ASK, WHO_FIND]),
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
                            {"columnMatch": "azure_id", "formatter": 13, "formatOptions": {"linkTarget": "Resource", "showIcon": False, "customColumnWidthSetting": "24ch"}},
                            _width("resource_kind", "16ch"),
                            _width("rg_col", "16ch"),
                            {**_who_formatter("who"), "formatOptions": {**_who_formatter("who")["formatOptions"], "customColumnWidthSetting": "18ch"}},
                            _width("detail", "48ch"),
                        ],
                        "labelSettings": [
                            {"columnId": "azure_id", "label": "ชื่อ"},
                            {"columnId": "resource_kind", "label": "ประเภท"},
                            {"columnId": "rg_col", "label": "อยู่ใน RG"},
                            {"columnId": "who", "label": "ต้องทำ"},
                            {"columnId": "detail", "label": "สิ่งที่ไม่ผ่าน"},
                            {"columnId": "owner_value", "label": "ค่า owner ที่มี"},
                        ],
                    },
                ),
                "name": "query - items",
            },
            _text(
                "text - owners",
                "## รายชื่อ owner สำหรับส่งเมล\n"
                "1 แถวต่อคน · owner ที่คั่นด้วยจุลภาคถูกแยกรายคน · ค่าว่างและ `nan` ไม่อยู่ในตารางนี้ (อยู่ในกลุ่ม หา owner ก่อน) · "
                "กด Export to Excel มุมขวาของตารางเพื่อนำไปส่งจากกล่องเมลทีม",
            ),
            {
                "type": 3,
                "content": _arg(
                    owners_q,
                    size=3,
                    visualization="table",
                    showExportToExcel=True,
                    exportToExcelOptions="visible",
                    noDataMessage="ไม่มี owner ที่ต้องติดต่อ",
                    gridSettings={
                        "rowLimit": 1000,
                        "filter": True,
                        "formatters": [
                            _width("owner", "32ch"),
                            {
                                "columnMatch": "email_ok",
                                "formatter": 18,
                                "formatOptions": {
                                    "customColumnWidthSetting": "18ch",
                                    "thresholdsOptions": "colors",
                                    "thresholdsGrid": [
                                        {"operator": "==", "thresholdValue": "ใช่", "representation": "transparent", "text": "{0}{1}"},
                                        {"operator": "Default", "thresholdValue": None, "representation": "redBright", "text": "{0}{1}"},
                                    ],
                                },
                            },
                            _width("n", "10ch"),
                        ],
                        "labelSettings": [
                            {"columnId": "owner", "label": "owner"},
                            {"columnId": "email_ok", "label": "อีเมลใช้ได้"},
                            {"columnId": "n", "label": "จำนวน"},
                            {"columnId": "entries", "label": "รายการและสิ่งที่ไม่ผ่าน"},
                        ],
                    },
                ),
                "name": "query - owners",
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
