# คู่มือดูแลระบบ (Operations)

คู่มือนี้เขียนแบบ "อยากทำอะไร ให้ทำแบบนี้" ทุกหัวข้อใช้ได้ทั้ง Windows PowerShell 5.1 และ PowerShell 7
การติดตั้งครั้งแรกดู [DEPLOY.md](DEPLOY.md) ส่วนค่า config ทั้งหมดดู [DEPLOY.md หัวข้อ 2](DEPLOY.md#2-configuration)

| อยากจะ... | ไปที่ |
|---|---|
| เตรียมตัวแปรก่อนรันคำสั่งในคู่มือนี้ | [0](#0-เตรียมตัวแปร-ทำทุกครั้งที่เปิด-powershell-ใหม่) |
| ดูว่าระบบยังทำงานอยู่ไหม / ทำไมสัปดาห์นี้ไม่มีเมล | [1](#1-ดูว่าระบบยังทำงานอยู่ไหม) |
| เปลี่ยนผู้รับเมล, หยุดส่งเมลชั่วคราว, เปลี่ยน SLA | [2](#2-เปลี่ยนค่า-config-ผู้รับเมล-หยุดส่ง-sla) |
| ส่งเมลทันทีโดยไม่รอวันจันทร์ / ดูตัวอย่างเมล | [3](#3-ส่งเมลทันที-หรือดูตัวอย่างเมล) |
| อัปเดตโค้ดหรือ Bicep ขึ้น production อย่างปลอดภัย | [4](#4-อัปเดต-production-อย่างปลอดภัย) |
| ถอยกลับหลังอัปเดตแล้วมีปัญหา | [5](#5-ถอยกลับ) |
| กู้ `state.json` ที่ถูกลบหรือเสีย | [6](#6-กู้-statejson) |
| ย้ายระบบไป RG หรือ subscription อื่น | [7](#7-ย้ายระบบไปที่ใหม่) |
| ลบระบบออก และเก็บของที่ค้าง | [8](#8-ลบระบบ) |
| งานที่ต้องทำตามรอบ (ทุกปี ฯลฯ) | [9](#9-งานตามรอบ) |
| ข้อควรระวังที่เจอบ่อย | [10](#10-ข้อควรระวัง) |

> [!WARNING]
> **ห้าม deploy ระบบนี้ 2 ชุดลง Resource Group เดียวกัน** (เช่น ทั้งแล็บและของจริงใน RG sandbox เดียวกัน)
> `teardown.ps1` ลบทุกอย่างที่ deployment ชื่อ `tag-governance-*` ใน RG นั้นสร้างไว้ การลบชุดหนึ่งจึงลบอีกชุดไปด้วย และ Workbook ของทั้งสองชุดจะเขียนทับกัน
> แล็บสำหรับทดสอบต้องอยู่คนละ RG หรือคนละ subscription เสมอ
> `deploy.ps1` จะหยุดให้เองถ้าเจอระบบนี้ที่ใช้ `NamePrefix` อื่นอยู่ใน RG แล้ว และ `teardown.ps1` จะลบเฉพาะชุดที่ `NamePrefix` ตรงกับ config
> ถ้ามี 2 ชุดอยู่แล้ว (deploy ด้วยสคริปต์รุ่นก่อน) ให้ลบชุดที่ไม่ใช้ด้วย `teardown.ps1 -ConfigPath <config ของชุดนั้น>` ตามหัวข้อ 8 แล้ว deploy ชุดที่เก็บไว้ซ้ำอีกครั้ง เพื่อให้ Workbook กลับมา

---

## 0. เตรียมตัวแปร (ทำทุกครั้งที่เปิด PowerShell ใหม่)

คำสั่งในคู่มือนี้ใช้ตัวแปรชุดนี้ แก้แค่บรรทัดแรกให้ชี้ไปที่ config ที่ต้องการ (production หรือแล็บ)

```powershell
$cfg    = './config/deploy.config.psd1'
$c      = Import-PowerShellDataFile $cfg
$rg     = $c.ResourceGroup
$prefix = if ($c.NamePrefix) { $c.NamePrefix } else { 'tagGov' }
az account set --subscription $c.SubscriptionId
$fn = az functionapp list -g $rg --query "[?starts_with(name, '$prefix-func-')].name | [0]" -o tsv
$st = az storage account list -g $rg --query "[?starts_with(name, 'st$($prefix.ToLower())')].name | [0]" -o tsv
"Function: $fn   Storage: $st"                     # ต้องได้ชื่อทั้งสองค่า ถ้าว่างแปลว่า config/subscription ผิด
```

ชื่อ resource หาจาก `NamePrefix` จึงใช้ได้แม้ RG จะมี resource ของคนอื่นปนอยู่

คำสั่ง `az storage ...` ในคู่มือนี้จะขึ้นข้อความ `There are no credentials provided...` ทุกครั้ง **เป็นเรื่องปกติ** (az ไปดึง key ให้เอง) ไม่ใช่ error

---

## 1. ดูว่าระบบยังทำงานอยู่ไหม

ระบบส่งเมลเฉพาะ **วันทำงานแรกของสัปดาห์ 09:00 น.** และ **ไม่ส่งถ้าทุกรายการผ่านแล้ว** สัปดาห์ที่ไม่มีเมลจึงอาจแปลว่า "ผ่านหมด" หรือ "ระบบพัง" ก็ได้ ตรวจแบบนี้

**ขั้นที่ 1 ดู snapshot ล่าสุด** (ทุกรอบที่ทำงานจริงจะบันทึกไฟล์ `snapshots/<วันที่>.json` ไว้เสมอ แม้ไม่ได้ส่งเมล)

```powershell
az storage blob list --account-name $st --auth-mode key -c tag-governance --prefix snapshots/ --query "[].name" -o tsv | Select-Object -Last 3
```

| ผลที่เห็น | แปลว่า |
|---|---|
| มีไฟล์ของวันทำงานแรกสัปดาห์นี้ | ระบบทำงานปกติ ถ้าไม่ได้เมล ดูตารางถัดไป |
| ไฟล์ล่าสุดเก่ากว่า 1 สัปดาห์ | ระบบไม่ได้ทำงาน ไปขั้นที่ 2 |

**ขั้นที่ 2 ดู error** เปิด Azure Portal > Application Insights `<NamePrefix>-ai` > **Logs** แล้ววาง query นี้ (KQL ต้องวางใน Portal **ไม่ใช่ PowerShell**)

```kusto
union traces, exceptions
| where timestamp > ago(14d)
| where message startswith "weekly_report" or itemType == "exception"
| project timestamp, itemType, message = coalesce(message, outerMessage)
| order by timestamp desc
```

`weekly_report: {"status": "skipped"...}` ในวันที่ไม่ใช่วันส่งเป็นเรื่องปกติ

**มี snapshot แต่ไม่ได้เมล**

| สาเหตุ | ตรวจ / แก้ |
|---|---|
| `MailEnabled` เป็น `$false` | ดูหัวข้อ 2 |
| ทุกรายการผ่านแล้ว | `summary.total` ใน snapshot เป็น 0 ระบบไม่ส่งเมลเมื่อไม่มีรายการค้าง |
| เมลอยู่ใน Junk | ผู้ส่งเป็น `DoNotReply@...azurecomm.net` ให้ผู้รับเพิ่มเป็น safe sender |
| ผู้รับผิด | `az functionapp config appsettings list -g $rg -n $fn --query "[?starts_with(name, 'TG_MAIL')].{name:name, value:value}" -o table` |

---

## 2. เปลี่ยนค่า config (ผู้รับเมล, หยุดส่ง, SLA)

ค่าทั้งหมดอยู่ในไฟล์ `config/deploy.config.psd1` **แก้ในไฟล์เสมอ** อย่าแก้ App settings ใน Portal เพราะการ deploy ครั้งถัดไปจะเขียนทับกลับ

1. แก้ค่าในไฟล์ config เช่น
   - เปลี่ยนผู้รับ: `MailTo`, `MailCc`, `MailCcEscalation`
   - หยุดส่งเมลชั่วคราว: `MailEnabled = $false` (ระบบยังเก็บ snapshot ต่อ) แล้ว deploy ด้วย `./scripts/deploy.ps1 -Part Infra`
   - เปลี่ยนจำนวนวันก่อนยกระดับ: `SlaDays`
2. ส่งค่าขึ้น Azure (ไม่แตะโค้ด ใช้เวลาราว 2-3 นาที)

```powershell
./scripts/deploy.ps1 -ConfigPath $cfg -Part Infra
```

3. ตรวจผล

```powershell
az functionapp config appsettings list -g $rg -n $fn --query "[?starts_with(name, 'TG_')].{name:name, value:value}" -o table
```

---

## 3. ส่งเมลทันที หรือดูตัวอย่างเมล

**ส่งเมลทันที** (ไม่กระทบรอบยกระดับของรายงานประจำสัปดาห์)

```powershell
./scripts/deploy.ps1 -ConfigPath $cfg -Part Infra -Set @{ EnableManualSend = $true }      # เปิดชั่วคราว
$key = az functionapp function keys list -g $rg -n $fn --function-name send_now --query default -o tsv
Invoke-RestMethod -Method Post -Headers @{ "x-functions-key" = $key } "https://$fn.azurewebsites.net/api/send" | ConvertTo-Json -Depth 6
./scripts/deploy.ps1 -ConfigPath $cfg -Part Infra                                        # ปิดกลับตามค่าในไฟล์
```

**ดูตัวอย่างเมลโดยไม่ส่งและไม่บันทึกอะไร**

```powershell
./scripts/deploy.ps1 -ConfigPath $cfg -Part Infra -Set @{ EnableTestEndpoint = $true }
$key = az functionapp function keys list -g $rg -n $fn --function-name run_now --query default -o tsv
Invoke-RestMethod -Headers @{ "x-functions-key" = $key } "https://$fn.azurewebsites.net/api/run?dry_run=1&force=1" | ConvertTo-Json -Depth 6
./scripts/deploy.ps1 -ConfigPath $cfg -Part Infra
```

ข้อมูลในเมลมาจากผลการตรวจของ Azure Policy ล่าสุด ถ้าเพิ่งแก้ tag แล้วอยากให้ตรวจใหม่ทันที

```powershell
az policy state trigger-scan --resource-group <ชื่อ RG ที่แก้ tag>     # ใช้เวลาหลายนาที
```

---

## 4. อัปเดต production อย่างปลอดภัย

ใช้เมื่อ merge โค้ดใหม่แล้ว และต้องการขึ้นของจริง

**ขั้นที่ 1 ทดสอบบนแล็บก่อน** (แล็บต้องอยู่คนละ RG กับของจริง ดูคำเตือนด้านบน)

```powershell
git pull
./scripts/deploy.ps1          # production ใช้ MailEnabled = $true; เปิด endpoint ทดสอบเฉพาะด้วย -Set
```

แล้วรันคำสั่ง "ดูตัวอย่างเมล" ในหัวข้อ 3 กับ environment ที่ใช้ทดสอบ ทดสอบเสร็จแล้วลบ resource ตามหัวข้อ 8

**ขั้นที่ 2 เลือกเวลา** อย่า deploy ช่วง **08:30-09:30 น. ของวันทำงานแรกของสัปดาห์** เพราะเป็นเวลาที่รอบส่งเมลทำงาน

**ขั้นที่ 3 ดูก่อนว่าจะเปลี่ยนอะไร**

```powershell
./scripts/deploy.ps1 -PlanOnly
```

อ่านผล what-if: `+ Create` และ `~ Modify` เป็นเรื่องปกติ **ถ้าเห็น `- Delete` หรือการ Replace storage account / Function / Key Vault ให้หยุด** และถามคนที่แก้โค้ดก่อน

**ขั้นที่ 4 deploy**

```powershell
./scripts/deploy.ps1              # ทั้งโครงสร้างและโค้ด
./scripts/deploy.ps1 -Part Code   # หรือเฉพาะโค้ด ถ้าแก้แค่ไฟล์ใน function/
```

ผลที่ถูกต้องต้องจบด้วย `พบ function: ...run_now, ...send_now, ...weekly_report`

---

## 5. ถอยกลับ

```powershell
git log --oneline -10                     # หา commit ก่อนหน้าที่ใช้งานได้
git checkout <commit>
./scripts/deploy.ps1
git checkout dev                          # กลับมา branch เดิมหลังถอยเสร็จ
```

- โค้ดและ App settings จะกลับเป็นแบบเดิมทันที
- การ deploy เป็นแบบเพิ่ม/แก้อย่างเดียว (incremental) **resource ที่เวอร์ชันใหม่เพิ่มเข้ามาจะยังอยู่** ซึ่งปกติไม่มีผลกับการทำงาน
- `state.json` ไม่ถูกแตะ อายุของรายการนับต่อตามเดิม

---

## 6. กู้ `state.json`

`state.json` เก็บวันที่พบแต่ละรายการครั้งแรกและสถานะการยกระดับ ถ้าหาย อายุของทุกรายการจะเริ่มนับใหม่ ระบบเปิด soft delete ไว้ จึง **กู้ได้ภายใน 14 วัน**

```powershell
az storage blob list --account-name $st --auth-mode key -c tag-governance --include d --query "[].{name:name, deleted:deleted}" -o table
az storage blob undelete --account-name $st --auth-mode key -c tag-governance -n state.json
```

ผลของ `undelete` ขึ้น `"undeleted": null` เป็นเรื่องปกติ รัน `blob list` อีกครั้งเพื่อยืนยันว่าไฟล์กลับมาแล้ว

ถ้าไฟล์ไม่ได้ถูกลบแต่ถูกเขียนทับด้วยข้อมูลผิด (เช่น เกิน 14 วันแล้ว หรือไม่มีใน soft delete) ให้คืนจากไฟล์สำรองตามหัวข้อ 7 ขั้นที่ 1 ถ้ามี

---

## 7. ย้ายระบบไปที่ใหม่

ใช้เมื่อย้ายไป RG หรือ subscription อื่น โดยให้อายุของรายการนับต่อ ทำในวันที่ **ไม่ใช่** วันทำงานแรกของสัปดาห์

```powershell
# 1) สำรอง state จากที่เดิม (ตั้งตัวแปรหัวข้อ 0 ด้วย config เดิมก่อน)
az storage blob download-batch --account-name $st --auth-mode key -s tag-governance -d ./backup --overwrite true

# 2) สร้าง config ใหม่ แล้ว deploy ที่ใหม่พร้อมคืน state
Copy-Item ./config/deploy.config.psd1 ./config/deploy.config-new.psd1      # แก้ SubscriptionId / ResourceGroup / Tags
./scripts/deploy.ps1 -ConfigPath ./config/deploy.config-new.psd1 -RestoreFrom ./backup

# 3) ตรวจที่ใหม่ (หัวข้อ 1 และ 3) แล้วลบที่เดิมตามหัวข้อ 8
```

- ถ้าที่ใหม่อยู่คนละ subscription ผู้ deploy ต้องมีสิทธิ์สร้าง role assignment ที่นั่น หาก deploy แจ้ง `AuthorizationFailed` ให้ผู้มีสิทธิ์ Owner หรือ User Access Administrator ช่วย แล้วรันใหม่ ดู [DEPLOY.md](DEPLOY.md)
- ผู้ส่งเมล (`DoNotReply@...azurecomm.net`) จะเปลี่ยนเป็นที่อยู่ใหม่ แจ้งผู้รับให้เพิ่มเป็น safe sender อีกครั้ง
- โฟลเดอร์ `backup/` มีข้อมูลจริง ห้าม commit (`.gitignore` กันไว้แล้ว) ลบทิ้งเมื่อย้ายเสร็จ

---

## 8. ลบระบบ

RG ของบริษัทเป็น sandbox ที่ใช้ร่วมกับคนอื่น **ห้ามใช้ `-DeleteResourceGroup`** ใช้ `teardown.ps1` ซึ่งลบเฉพาะของระบบนี้

```powershell
./scripts/teardown.ps1 -ConfigPath $cfg                                 # 1) ดูรายการที่จะลบก่อน ยังไม่ลบอะไร
./scripts/teardown.ps1 -ConfigPath $cfg -BackupTo ./backup -Execute     # 2) สำรอง state แล้วลบ (ต้องพิมพ์ชื่อ RG ยืนยัน)
```

ก่อนสั่งขั้นที่ 2 ตรวจรายการในขั้นที่ 1 ว่า **มีแต่ชื่อที่ขึ้นต้นด้วย `NamePrefix` ของคุณ** (เช่น `tagGov-func-...`, `sttaggov...`) ถ้า `resource ที่จะลบ (0)` หรือมีชื่อของคนอื่นปน ให้หยุด

สคริปต์ทำครบให้เอง: เพิกถอนสิทธิ์ Reader, ลบ resource, purge Key Vault และ Log Analytics

**ถ้า teardown ไม่ครบ** (เช่น error กลางทาง หรือมีคนลบ RG ไปเองแล้ว) ให้เก็บของค้าง 2 อย่างนี้

```powershell
# Key Vault ที่ค้างใน soft-delete (ไม่ purge แล้ว deploy ใหม่จะชนชื่อ)
az keyvault list-deleted --query "[?starts_with(name, '$prefix')].{name:name, location:properties.location}" -o table
az keyvault purge --name <ชื่อ> --location <location>

# สิทธิ์ Reader ที่เจ้าของ (Function) ถูกลบไปแล้ว: แถวที่ name ว่าง
az role assignment list --scope "/subscriptions/$($c.SubscriptionId)" --role Reader --query "[?principalType=='ServicePrincipal'].{name:principalName, id:id}" -o table
az role assignment delete --ids <id ของแถวที่ name ว่าง>
```

ระวังอย่าลบแถว Reader ที่ยังมีชื่ออยู่ เพราะอาจเป็นของระบบอื่น

---

## 9. งานตามรอบ

| เมื่อไหร่ | งาน | วิธีทำ |
|---|---|---|
| **ทุกปี ก่อน 1 มกราคม** | ใส่วันหยุดปีถัดไปใน `function/holidays.json` (ตอนนี้มีถึง 2026-12-31) ถ้าไม่ใส่ ระบบยังทำงาน แต่จะส่งเมลในวันจันทร์ที่เป็นวันหยุดแทนที่จะเลื่อนไปวันถัดไป | แก้ไฟล์ commit แล้วทำหัวข้อ 4 ด้วย `-Part Code` |
| ทุกครั้งที่ทดสอบเสร็จ | ปิด endpoint ทดสอบ (`EnableTestEndpoint`, `EnableManualSend` เป็น `$false`) | `./scripts/deploy.ps1 -ConfigPath $cfg -Part Infra` |
| ถ้า function key อาจรั่ว (เช่น เผลอแปะในแชต) | สร้าง key ใหม่ | Portal > Function App > เลือก function > Function Keys > Renew |
| ทุก 3-6 เดือน | ดูค่าใช้จ่าย ปกติไม่เกินราว $1-2 ต่อเดือน | Portal > Cost Management กรองด้วย tag ของโปรเจกต์ |
| ทุก 3-6 เดือน | ตรวจว่า Defender for Storage ไม่ได้คิดเงิน storage ของระบบนี้ (ได้ `Free` คือไม่คิด) | `az security pricing show -n StorageAccounts --query pricingTier -o tsv` |
| ก่อนปลายปี 2027 | Python 3.11 และ Linux Consumption plan จะหมดอายุการสนับสนุนจาก Microsoft ต้องอัปเกรดก่อน | งานของนักพัฒนา เปิด issue ไว้ล่วงหน้า |

---

## 10. ข้อควรระวัง

- **KQL ไม่ใช่คำสั่ง PowerShell** query ที่ขึ้นต้นด้วย `traces`, `requests`, `union` ต้องวางในหน้า Logs ของ Application Insights ใน Portal ถ้าวางใน PowerShell จะได้ error `The term '1h' is not recognized`
- **`--query` ของ az บน Windows PowerShell 5.1** ถ้ามีวงเล็บ `( )` ให้มีช่องว่างอย่างน้อย 1 ตัวใน query (เช่น `starts_with(name, 'x')`) ไม่งั้น cmd.exe จะตีความวงเล็บเองแล้ว error `... was unexpected at this time`
- **error ของ `Invoke-RestMethod`** บน PowerShell 5.1 ไม่แสดงข้อความจาก server ให้ดูที่ตัวเลข `(400)`, `(401)`, `(404)` แล้วเทียบกับตาราง Troubleshooting ใน [DEPLOY.md](DEPLOY.md#5-troubleshooting)
- **แก้ค่าใน config เสมอ** การแก้ App settings ใน Portal ตรงๆ จะถูกเขียนทับในการ deploy ครั้งถัดไป
- **ไฟล์ config จริง** (`config/*.psd1` ที่ไม่ใช่ `.example`) และ `backup/` ห้าม commit ถ้าจะส่งต่อให้คนอื่น ให้ส่งไฟล์ทางช่องทางภายใน
