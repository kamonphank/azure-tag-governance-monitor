# Deployment Guide

คู่มือ deploy ระบบขึ้นระบบจริงของบริษัท ภาพรวมของระบบอยู่ใน [README](../README.md) ส่วนการทดสอบแบบลบแล้วสร้างใหม่ในห้องแล็บอยู่ใน [QUICKSTART](QUICKSTART.md)

**Contents**

1. [Deploy to production](#1-deploy-to-production)
2. [Configuration](#2-configuration)
3. [Testing](#3-testing)
4. [Update and removal](#4-update-and-removal)
5. [Troubleshooting](#5-troubleshooting)
6. [For developers](#6-for-developers)

## 1. Deploy to production

ทำตามลำดับ ตั้งแต่เครื่องที่ยังไม่มีอะไรจนระบบพร้อมใช้ ใช้เวลาประมาณ 15 นาที

### Step 1: เตรียมเครื่องและสิทธิ์

| Item | Version | หมายเหตุ |
|---|---|---|
| PowerShell | 7 ขึ้นไป (5.1 ก็ใช้ได้) | ตรวจด้วย `$PSVersionTable.PSVersion` |
| Azure CLI (`az`) | ล่าสุด | ตรวจด้วย `az version` อัปเดตด้วย `az upgrade` |
| Bicep | ล่าสุด | ติดตั้งมากับ Azure CLI อัปเดตด้วย `az bicep upgrade` (Bicep เก่ามีบั๊กทำให้ compile ไม่ผ่าน) |
| Git | เวอร์ชันใดก็ได้ | ใช้ clone |

สิ่งที่ต้องมีก่อน deploy

- **Policy assignment** ที่ตรวจ tag อยู่แล้ว จาก repository [azure-policy-rg-vm-tag-governance](https://github.com/kamonphank/azure-policy-rg-vm-tag-governance) และจดชื่อ assignment ไว้
- **สิทธิ์ของผู้ deploy**

| Task | Required permission |
|---|---|
| สร้าง Resource Group ใหม่ | Contributor ระดับ subscription |
| สร้าง resource ใน Resource Group เดิม | Contributor บน Resource Group นั้น |
| มอบสิทธิ์ Reader และ Key Vault ให้ Function | Owner หรือ User Access Administrator ที่ subscription |

หากไม่มีสิทธิ์ข้อสุดท้าย ให้ administrator ช่วย deploy

### Step 2: Clone repository

```powershell
git clone https://github.com/kamonphank/azure-tag-governance-monitor.git
cd azure-tag-governance-monitor
git checkout feature/azure-tag-governance-init   # เปลี่ยนเป็น main เมื่อ merge เข้า main แล้ว
```

### Step 3: Login และเลือก subscription

```powershell
az login
az account set --subscription <subscription-id>
az bicep upgrade
```

สคริปต์เทียบ subscription ที่ใช้งานอยู่กับ `SubscriptionId` ใน config และหยุดทันทีหากไม่ตรง เพื่อป้องกัน deploy ผิด subscription

### Step 4: ตั้งค่า config

```powershell
Copy-Item config/team.example.psd1 config/prod.psd1
```

แก้ไฟล์ `config/prod.psd1` ให้ครบ ค่าที่ต้องแก้มีดังนี้ ค่าอื่นใช้ค่าเริ่มต้นได้เลย

```powershell
@{
    SubscriptionId    = '<subscription-id>'
    ResourceGroup     = '<resource-group>'
    Location          = 'southeastasia'
    Tags              = @{ '<tag-name>' = '<value>' }   # ตามที่ Policy บังคับ ใส่ให้ Resource Group ใหม่และทุก resource
    MailTo            = @('<responsible-person-email>')  # ผู้รับอีเมลสรุปทุกฉบับ
    MailCc            = @()                              # Cc ทุกฉบับ (ไม่บังคับ)
    MailCcEscalation  = @('<manager-email>')             # Cc เพิ่มเมื่อมีรายการค้างเกินกำหนดสองรอบ
    MailEnabled       = $false                           # เริ่มด้วย $false (ดู Step 7)
}
```

ถ้าต้องการให้ส่งอีเมลรายงานฉบับแรกทันทีที่ deploy เสร็จ ให้ตั้งสามค่านี้เพิ่ม สคริปต์จะส่งผ่าน `POST /api/send` และบันทึก snapshot แรกให้ (ข้าม Step 7 ส่วนบันทึก snapshot ได้)

```powershell
    MailEnabled        = $true
    EnableManualSend   = $true
    SendReportOnDeploy = $true
```

- ไฟล์ `config/*.psd1` (ยกเว้น `*.example.psd1`) ถูก `.gitignore` กันไว้ จึงไม่ถูก push ห้ามแก้ไฟล์ตัวอย่างให้เป็นค่าจริง และห้ามใส่ข้อมูลลับในไฟล์ config
- ถ้าใช้ ACS Email เดิมแทนการสร้างใหม่ ให้ตั้ง `CreateAcsEmail = $false`, `ExistingAcsSender` และตัวแปร `$env:TG_ACS_CONNECTION_STRING = '<connection-string>'` ในหน้าต่าง PowerShell เดียวกับที่รัน deploy

### Step 5: ตรวจสอบก่อน deploy

```powershell
./scripts/deploy.ps1 -ConfigPath ./config/prod.psd1 -PlanOnly
```

สคริปต์ตรวจ config แสดงสรุปสิ่งที่จะทำ และบอกว่า Resource Group มีอยู่แล้วหรือไม่ โดยไม่เปลี่ยนแปลงสิ่งใด หากมี error สคริปต์ระบุจุดที่ผิด

### Step 6: Deploy

```powershell
./scripts/deploy.ps1 -ConfigPath ./config/prod.psd1
```

สคริปต์ถามยืนยันก่อนทุกครั้ง

- Resource Group ใหม่: พิมพ์ `yes`
- Resource Group ที่มีอยู่แล้ว: พิมพ์ **ชื่อ Resource Group** (สคริปต์เพิ่ม resource ของโปรเจกต์นี้ ไม่ลบหรือแก้ resource อื่น และไม่แก้ tag หรือ region ของ Resource Group ส่วน `Tags` ใส่ให้เฉพาะ resource ของโปรเจกต์นี้)

จากนั้นสคริปต์สร้าง resource ทั้งชุด (Storage, Function App, Key Vault, Log Analytics, Application Insights, Workbook, ACS Email) ให้สิทธิ์ Reader แก่ Function แล้วส่งโค้ดขึ้น Function App ท้ายสุดสคริปต์พิมพ์ขั้นตอนถัดไปให้

### Step 7: ตรวจสอบและเริ่มเก็บข้อมูล

รอ 2-3 นาทีให้สิทธิ์แพร่กระจาย แล้วตรวจที่ Azure Portal

- **Function App** สถานะ Running
- **Function App > Environment variables** แถว `TG_ACS_CONNECTION_STRING` มีเครื่องหมายถูกสีเขียว (อ่าน secret จาก Key Vault ได้)
- **Monitor > Workbooks > Shared > "Tag Governance"** เปิดได้ และตัวเลขใกล้เคียงหน้า Policy compliance

ถ้าตั้ง `SendReportOnDeploy = $true` สคริปต์ส่งอีเมลฉบับแรกและบันทึก snapshot แรกให้แล้ว (ดูผลท้ายสคริปต์ในหัวข้อ "ส่งอีเมลรายงานทันที") ข้ามส่วนที่เหลือของ Step 7 ได้

ถ้าไม่ได้ตั้ง ให้บันทึก snapshot แรกทันที เพื่อให้ระบบเริ่มนับอายุของรายการตั้งแต่วันนี้ (ถ้าไม่ทำ ระบบจะเริ่มนับในวันทำงานแรกของสัปดาห์ถัดไป) โดยเปิด endpoint ทดสอบ `/api/run` ชั่วคราวด้วย `-Set` แล้วปิดกลับ

```powershell
$cfg = './config/prod.psd1'
$rg = '<resource-group>'; $fn = '<function-app>'   # ชื่อ Function App อยู่ในผลของ deploy.ps1 (บรรทัด "Function App:")

./scripts/deploy.ps1 -ConfigPath $cfg -Part Infra -Set @{ EnableTestEndpoint = $true }   # เปิด /api/run ชั่วคราว
$key = az functionapp function keys list -g $rg -n $fn --function-name run_now --query default -o tsv

Invoke-RestMethod "https://$fn.azurewebsites.net/api/run?code=$key&dry_run=1&force=1" | ConvertTo-Json -Depth 6   # ดูผลก่อน ไม่บันทึกอะไร
Invoke-RestMethod "https://$fn.azurewebsites.net/api/run?code=$key&dry_run=0&force=1" | ConvertTo-Json -Depth 6   # บันทึก snapshot แรก เรียกครั้งเดียว

./scripts/deploy.ps1 -ConfigPath $cfg -Part Infra   # ปิด /api/run กลับตามค่าใน config
```

- ผลของ `dry_run=1` ต้องมี `"status": "ok"` และ `summary.total` ใกล้เคียงหน้า Policy compliance
- ผลของ `dry_run=0` ต้องมี `"dry_run": false` และเพราะ `MailEnabled` ยังเป็น `$false` ระบบจะไม่ส่งอีเมล แต่บันทึก `state.json` และ `snapshots/<date>.json` ใน Blob container `tag-governance`
- `$key` คือ function key ดูคำอธิบายในหัวข้อ [Testing](#3-testing)

ปล่อยให้ระบบเก็บ snapshot ไปอย่างน้อย 1 สัปดาห์เพื่อให้มีข้อมูลอายุของรายการ แล้วเปิดส่งอีเมล

```powershell
# แก้ MailEnabled = $true ใน config/prod.psd1 แล้วรัน
./scripts/deploy.ps1 -ConfigPath ./config/prod.psd1 -Part Infra
```

ทดสอบเพิ่มเติมได้ตามหัวข้อ [Testing](#3-testing)

### Checklist ก่อนใช้งานจริง

- [ ] ทดสอบในห้องแล็บตาม [QUICKSTART](QUICKSTART.md) และได้รับอนุมัติตามขั้นตอนของบริษัท
- [ ] ยืนยันสถานะของ ACS Email ที่ https://aka.ms/acs-retirement และขอให้ผู้ดูแลอีเมลอนุญาตผู้ส่งจาก `azurecomm.net` (อีเมลมักมี banner "external sender" และอาจเข้า Junk)
- [ ] ตรวจสอบ `function/holidays.json` กับปฏิทินของบริษัท
- [ ] กำหนดผู้ดูแล Function ภายหลังสิ้นสุดโครงการ
- [ ] จำกัดผู้มีสิทธิ์ Contributor บน Resource Group เพราะ storage key ยังอยู่ใน App settings (Consumption plan ต้องใช้ key นี้กับ Azure Files จึงย้ายไป Key Vault ไม่ได้) ส่วน ACS connection string เก็บใน Key Vault และ Function อ่านผ่าน managed identity

## 2. Configuration

config เป็น PowerShell data file (`.psd1`) ซึ่งเป็นข้อมูลล้วน สคริปต์ไม่รันโค้ดใดในไฟล์ และตรวจค่าก่อนทำงาน หยุดพร้อมแจ้งจุดที่ผิด เช่น key ที่ไม่รู้จัก GUID ไม่ถูกต้อง หรืออีเมลที่ยังเป็น `example.com`

| Config key | Required | Default | Description | App setting |
|---|---|---|---|---|
| `SubscriptionId` | Yes | - | subscription ที่ deploy ลง และที่ Function ได้รับสิทธิ์ Reader | - |
| `ResourceGroup` | Yes | - | ชื่อ Resource Group (มีแล้วจะ deploy เพิ่ม ยังไม่มีจะสร้างใหม่) | - |
| `Location` | Yes | - | region ของ Resource Group ใหม่ เช่น `southeastasia` | - |
| `MailTo` | Yes | - | ผู้รับหลักของอีเมลสรุปทุกฉบับ ต้องเป็นอีเมลจริง | `TG_MAIL_TO` |
| `Tags` | No | `@{}` | tag ที่ใส่ให้ Resource Group ที่สร้างใหม่และทุก resource ของโปรเจกต์ (Storage, Function App, Key Vault ฯลฯ) ควรครบตามที่ Policy บังคับ Resource Group ที่มีอยู่แล้วไม่ถูกแก้ tag (`ResourceGroupTags` คือชื่อเดิม ยังใช้ได้) | - |
| `NamePrefix` | No | `tagGov` | คำนำหน้าชื่อ resource (ตัวอักษรหรือตัวเลข 1 ถึง 8 ตัว) | - |
| `PolicyAssignmentName` | No | `rg-tag-governance-audit` | ชื่อ Policy assignment (ไม่ใช่ ID เต็ม) ตรวจสอบด้วย `az policy assignment list --query "[].name" -o tsv` | `TG_ASSIGNMENT_NAME` |
| `ScanSubscriptionIds` | No | `@()` | จำกัด subscription ที่ scan ว่างคือทุก subscription ที่ Function อ่านได้ | `TG_SUBSCRIPTION_IDS` |
| `RgNameRegex` | No | ว่าง | กรองเฉพาะ Resource Group ที่ชื่อตรง regex โดยปกติไม่ต้องใช้ | `TG_RG_NAME_REGEX` |
| `SlaDays` | No | `14` | จำนวนวันที่ค้างก่อนเข้าสู่ Stage 1 | `TG_SLA_DAYS` |
| `MailEnabled` | No | `$false` | `$false` คือไม่ส่งอีเมล (เก็บเฉพาะ snapshot และ state) | `TG_MAIL_ENABLED` |
| `MailCc` | No | `@()` | Cc ของอีเมลสรุปทุกฉบับ | `TG_MAIL_CC` |
| `MailCcEscalation` | No | `@()` | Cc เพิ่มเติมเฉพาะอีเมลที่มีรายการ Stage 2 | `TG_MAIL_CC_ESCALATION` |
| `CreateAcsEmail` | No | `$true` | `$true` คือสร้าง ACS Email ใหม่ `$false` คือใช้ ACS เดิม | `TG_MAIL_SENDER`, `TG_ACS_CONNECTION_STRING` |
| `ExistingAcsSender` | เมื่อ `CreateAcsEmail = $false` | ว่าง | ที่อยู่ผู้ส่งของ ACS เดิม | `TG_MAIL_SENDER` |
| `AssignSubscriptionReader` | No | `$true` | ให้สคริปต์มอบสิทธิ์ Reader แก่ Function | - |
| `EnableTestEndpoint` | No | `$false` | เปิด endpoint `/api/run` สำหรับทดสอบ | `TG_HTTP_ENABLED` |
| `EnableManualSend` | No | `$false` | เปิด endpoint `POST /api/send` สำหรับส่งอีเมลรายงานทันทีตอนไหนก็ได้ | `TG_MANUAL_SEND_ENABLED` |
| `SendReportOnDeploy` | No | `$false` | ให้ `deploy.ps1` ส่งอีเมลรายงานจริงทันทีหลัง deploy (`-Part All` หรือ `Code`) ต้องตั้ง `MailEnabled` และ `EnableManualSend` เป็น `$true` ด้วย ส่ง 1 ฉบับทุกครั้งที่ deploy ถ้าแก้โค้ดแล้วไม่อยากส่ง ใช้ `-Set @{ SendReportOnDeploy = $false }` | - |

ข้อควรทราบ

- **`MailEnabled = $false`** ระบบไม่บันทึกว่ารายการถูก escalate เมื่อเปิดส่งอีเมลภายหลัง รายการที่ค้างนานจะเริ่มที่ Stage 1 เสมอ ไม่ข้ามไป Stage 2 จึงแนะนำให้เริ่มด้วย `$false` อย่างน้อย 1 สัปดาห์
- **Cc** หากอีเมลใน `MailCc` และ `MailCcEscalation` ซ้ำกัน ระบบใส่เพียงครั้งเดียว
- **สิทธิ์ Reader** สคริปต์มอบให้เฉพาะ subscription ใน `SubscriptionId` หากต้องการ scan subscription อื่น administrator ต้องมอบสิทธิ์ให้เอง
- **`EnableTestEndpoint`** ปิดไว้เป็นค่าเริ่มต้น เพราะ `dry_run=0` ส่งอีเมลและบันทึก state ได้จริง เปิดเฉพาะตอนทดสอบ
- **`EnableManualSend`** ใช้ส่งอีเมลนอกรอบ (นอกเหนือจากรอบอัตโนมัติวันทำงานแรกของสัปดาห์) โดยไม่บันทึก state และ snapshot รอบ escalation ของรายงานประจำสัปดาห์จึงไม่เปลี่ยน ดูหัวข้อ 3

**ตัวเลือกของ `deploy.ps1`**

| Option | Description |
|---|---|
| `-ConfigPath <path>` | ใช้ไฟล์ config อื่น (ค่าเริ่มต้น `config/deploy.config.psd1`) |
| `-PlanOnly` | แสดงสรุป และรัน what-if หาก Resource Group มีอยู่แล้ว โดยไม่เปลี่ยนแปลงสิ่งใด |
| `-Yes` | ข้ามขั้นตอนการยืนยัน เหมาะกับการรันอัตโนมัติ |
| `-Part Infra` / `-Part Code` | deploy เฉพาะโครงสร้างและ App settings / ส่งเฉพาะโค้ด Function |
| `-Set @{ Key = Value }` | ทับค่าใน config จากบรรทัดคำสั่งชั่วคราว ไม่ถูกบันทึกลงไฟล์ ค่าที่ต้องคงอยู่ควรอยู่ในไฟล์ config |
| `-RestoreFrom <dir>` | คืน state ที่สำรองไว้ด้วย `teardown.ps1 -BackupTo` หลัง deploy |

## 3. Testing

1. **Workbook** เปิด Azure Portal ไปที่ Monitor, Workbooks, Shared แล้วเลือก "Tag Governance" และเทียบตัวเลขกับหน้า Policy compliance
2. **Dry run** ตั้ง `EnableTestEndpoint = $true` แล้วรัน `-Part Infra` จากนั้นเรียกโดยไม่ส่งอีเมลและไม่บันทึก state

```powershell
$rg = '<resource-group>'; $fn = '<function-app>'
$key = az functionapp function keys list -g $rg -n $fn --function-name run_now --query default -o tsv
Invoke-RestMethod "https://$fn.azurewebsites.net/api/run?code=$key&dry_run=1&force=1" | ConvertTo-Json -Depth 6
```

**Function key** endpoint `/api/run` และ `/api/send` กำหนดให้ผู้เรียกต้องแนบ key ใน `?code=` ทุกครั้ง (auth level `FUNCTION`) ถ้าไม่มีหรือผิดจะได้ `401` ซึ่งป้องกันไม่ให้คนที่รู้แค่ URL สั่งส่งอีเมลหรือแก้ state ได้ Azure สร้าง key ชื่อ `default` ให้แต่ละ function อัตโนมัติ คำสั่ง `az functionapp function keys list` ใช้สิทธิ์ Azure ของผู้ที่ login อยู่ไปอ่าน key นั้นมา จึงต้องดึงแยกตามชื่อ function (`run_now` หรือ `send_now`) ถือว่า key เป็นความลับ ห้ามแปะลงเอกสารหรือแชต หากรั่วให้สร้างใหม่ที่ Portal > Function App > เลือก function > Function Keys > Renew

ตัวอย่างในเอกสารนี้ใช้ `Invoke-RestMethod` ซึ่งเป็นคำสั่งของ PowerShell เอง ใช้ได้ทั้ง Windows PowerShell 5.1 และ PowerShell 7 และต่อ `| ConvertTo-Json -Depth 6` เพื่อให้เห็นผลเป็น JSON ครบทุกระดับ (ถ้าไม่ต่อ ค่าที่เป็น list จะแสดงเป็น `System.Object[]`) ไม่ควรใช้ `curl` ใน Windows PowerShell 5.1 เพราะเป็น alias ของ `Invoke-WebRequest` ซึ่งไม่รู้จัก option ของ curl เช่น `-X POST` หากต้องการ curl จริงให้พิมพ์ `curl.exe`

ผลที่ถูกต้องมี `"status": "ok"` พร้อม `summary` (จำนวนรายการ) และตัวอย่างอีเมลที่ระบบจะส่ง (เมื่อมีรายการค้าง)

| Parameter | Description |
|---|---|
| `dry_run` | `1` คือไม่ส่งอีเมลและไม่บันทึก state (ค่าเริ่มต้น) `0` คือทำงานจริง |
| `force` | `1` คือข้ามการตรวจสอบว่าวันนี้เป็นวันส่งหรือไม่ |
| `today` | วันที่ `YYYY-MM-DD` ใช้จำลองวัน เช่น +14 และ +21 วันเพื่อดู Stage 1 และ Stage 2 |

3. **ส่งอีเมลจริงหนึ่งครั้ง** (ถ้าต้องการ) หลังตั้ง `MailEnabled = $true` ให้เรียก `dry_run=0&force=1` แล้วตรวจว่าอีเมลถึงผู้รับ และมี `state.json` กับ `snapshots/<date>.json` ใน Blob container `tag-governance`
4. **ปิด endpoint ทดสอบกลับ** ตั้ง `EnableTestEndpoint = $false` แล้วรัน `-Part Infra`

ห้ามใช้ `dry_run=0` ร่วมกับ `today` ที่เป็นวันในอนาคต เพราะจะบันทึก state ที่ไม่ตรงกับความเป็นจริง

**ส่งอีเมลทันทีตอนไหนก็ได้** ตั้ง `EnableManualSend = $true` แล้วรัน `-Part Infra` จากนั้นเรียก

```powershell
$rg = '<resource-group>'; $fn = '<function-app>'
$key = az functionapp function keys list -g $rg -n $fn --function-name send_now --query default -o tsv
Invoke-RestMethod -Method Post "https://$fn.azurewebsites.net/api/send?code=$key" | ConvertTo-Json -Depth 6
```

key ของแต่ละ function แยกกัน ต้องดึง key ของ `send_now` ไม่ใช่ของ `run_now` เรียกแต่ละครั้งส่งอีเมล 1 ฉบับ (ดูได้จาก `message_id` ในผลลัพธ์)

endpoint นี้ส่งอีเมลด้วยข้อมูลล่าสุดทันทีโดยไม่สนว่าเป็นวันส่งหรือไม่ แต่ยังเคารพ `MailEnabled` และไม่ส่งเมื่อทุกรายการผ่านแล้ว ระบบไม่บันทึก state และ snapshot จากการเรียกนี้ จึงไม่ทำให้รายการขยับไป Stage 2 เร็วกว่ารอบประจำสัปดาห์ (ต่างจาก `run?dry_run=0&force=1` ที่บันทึก state) ยกเว้นครั้งแรกที่ยังไม่เคยมี state เลย ระบบจะบันทึก snapshot แรกให้ (`"persist": true` ในผลลัพธ์)

## 4. Update and removal

**Update** แก้โค้ดหรือ `holidays.json` แล้วรัน `-Part Code` แก้ config แล้วรัน `-Part Infra`

**Removal และเริ่มใหม่** ใช้ `scripts/teardown.ps1` ซึ่งอ่าน config เดียวกับ `deploy.ps1` และลบเฉพาะ resource ที่ deployment ของโปรเจกต์นี้สร้าง (ไม่แตะ resource อื่นใน Resource Group) พร้อมเพิกถอนสิทธิ์ Reader และ purge Key Vault / Log Analytics ที่ค้างใน soft-delete ซึ่งหากไม่ purge การ deploy ใหม่ด้วยชื่อเดิมจะชน

```powershell
./scripts/teardown.ps1 -ConfigPath ./config/prod.psd1                              # ดูรายการที่จะลบ (ยังไม่ลบ)
./scripts/teardown.ps1 -ConfigPath ./config/prod.psd1 -BackupTo ./backup -Execute # สำรอง state แล้วลบ (ต้องพิมพ์ชื่อ Resource Group ยืนยัน)
./scripts/deploy.ps1 -ConfigPath ./config/prod.psd1 -RestoreFrom ./backup          # deploy ใหม่ และคืน state ให้อายุของรายการนับต่อ
```

- ถ้าไม่ใช้ `-BackupTo` ไฟล์ `state.json` จะหาย และอายุของรายการทั้งหมดเริ่มนับใหม่
- ใช้ `-DeleteResourceGroup` เมื่อ Resource Group สร้างมาเพื่อระบบนี้โดยเฉพาะ
- โฟลเดอร์ `backup/` มีชื่อ resource จริง ห้าม commit (ถูก `.gitignore` กันไว้แล้ว)

## 5. Troubleshooting

| Symptom | Cause and resolution |
|---|---|
| สคริปต์แจ้งว่า `az login` อยู่คนละ subscription | ใช้ `az account set --subscription <id>` |
| Bicep compile ไม่ผ่าน หรือ crash | Bicep เก่าเกินไป รัน `az bicep upgrade` |
| `AuthorizationFailed` ขณะมอบสิทธิ์ Reader หรือ Key Vault | ไม่มีสิทธิ์ Owner หรือ User Access Administrator ให้ administrator deploy |
| `TG_ACS_CONNECTION_STRING` ขึ้นเครื่องหมายแดง | สิทธิ์ยังไม่แพร่กระจาย รอ 2-3 นาที แล้วรีสตาร์ต Function App |
| ชื่อ resource ซ้ำ | เปลี่ยน `NamePrefix` |
| deploy ใหม่ชนชื่อ Key Vault หรือ Log Analytics | ของเก่าค้างใน soft-delete รัน `teardown.ps1` ซึ่ง purge ให้ หรือเปลี่ยน `NamePrefix` |
| Function App ไม่มี function ในหน้า Overview หลัง deploy | รัน `./scripts/deploy.ps1 -Part Code` อีกครั้ง (สคริปต์รุ่นก่อนสร้าง zip ด้วย `\` เมื่อรันบน Windows PowerShell 5.1 และ `-Part Infra` ลบ `WEBSITE_RUN_FROM_PACKAGE` ทิ้ง) หากยังว่าง ดู import error ที่ Log stream หรือ Application Insights |
| Function ได้ผลลัพธ์ว่าง | ตรวจสอบว่ามีสิทธิ์ Reader, `PolicyAssignmentName` ตรงกับ assignment และ Policy ประเมินเสร็จแล้ว (ใช้ `az policy state trigger-scan` ได้) |
| ไม่ได้รับอีเมล | `MailEnabled` ยังเป็น `$false` อีเมลอยู่ใน Junk หรือทุกรายการผ่านแล้ว (ระบบไม่ส่งอีเมลเมื่อไม่มีรายการค้าง) |
| `/api/run` ตอบ 404 | `EnableTestEndpoint` ยังเป็น `$false` |
| `/api/send` ตอบ 404 | `EnableManualSend` ยังเป็น `$false` ดูหัวข้อ 3 |

## 6. For developers

repository นี้เป็น public ก่อน commit และ push ทุกครั้งควรตรวจสอบด้วยตนเองว่าไม่มีข้อมูลจริง เช่น subscription ID, อีเมล, ชื่อบริษัท หรือชื่อระบบภายใน ปะปนอยู่ ด้วย `git status` และ `git diff --staged` ไฟล์ config จริงและไฟล์ข้อมูล (`*.csv`, `*.xlsx`, `state.json`) ถูกกำหนดใน `.gitignore` แล้ว ควรเปิด Secret scanning และ Push protection ใน GitHub ด้วย

- **รัน test suite** (ไม่ต้องใช้ Azure) ด้วย `pip install -r function/requirements.txt pytest` แล้ว `python -m pytest tests -q`
- **รัน Function ในเครื่อง** คัดลอก `function/local.settings.sample.json` เป็น `function/local.settings.json` (ไม่ถูก push) ระบุค่า `TG_*` ตามตารางหัวข้อ 2 แล้วรัน `func start`
- **กรณีเผลอ push ข้อมูลจริง** ให้ถือว่าข้อมูลรั่วไหลแล้ว เปลี่ยนค่า key ที่เกี่ยวข้องทันที แจ้งทีม security ล้างประวัติด้วย `git filter-repo` (หรือสร้าง repository ใหม่จากโค้ดที่สะอาด) แล้ว force-push
