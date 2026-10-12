# Deployment Guide

เอกสารนี้อธิบายการ deploy ระบบและความหมายของค่าใน config ส่วนภาพรวมของระบบอยู่ใน [README](../README.md)

**Contents**

1. [Overview](#1-overview)
2. [Prerequisites](#2-prerequisites)
3. [Deployment steps](#3-deployment-steps)
4. [Configuration](#4-configuration)
5. [Environment variables](#5-environment-variables)
6. [Assigning the Reader role](#6-assigning-the-reader-role)
7. [Post-deployment testing](#7-post-deployment-testing)
8. [Rollout, update and removal](#8-rollout-update-and-removal)
9. [Troubleshooting](#9-troubleshooting)
10. [For developers](#10-for-developers)

## 1. Overview

สคริปต์ `./scripts/deploy.ps1` deploy ระบบทั้งหมดลงใน Resource Group เดียว โดยอ่านค่าจาก `config/deploy.config.psd1` ตามลำดับดังนี้

1. ตรวจสอบ config และตรวจว่า `az login` อยู่ใน subscription ที่ระบุ
2. ตรวจสอบ Resource Group และขอให้ผู้ใช้ยืนยัน
3. สร้าง Resource Group (หากยังไม่มี) และ deploy Bicep
4. ส่งโค้ดในโฟลเดอร์ `function/` ขึ้น Function App

resource ที่ถูกสร้างมี Storage account, Function App (Linux Consumption), Log Analytics, Application Insights, Workbook และ ACS Email (เมื่อ `CreateAcsEmail = $true`) โดยชื่อขึ้นต้นด้วย `NamePrefix` หาก `AssignSubscriptionReader = $true` สคริปต์จะมอบสิทธิ์ Reader ระดับ subscription ให้ managed identity ของ Function ด้วย

สคริปต์ไม่ลบ resource ใด เป็นการ deploy แบบ incremental และไม่แก้ไข resource อื่นใน Resource Group เดียวกัน

## 2. Prerequisites

- PowerShell 5.1 หรือ 7 ขึ้นไป และ [Azure CLI](https://learn.microsoft.com/cli/azure/install-azure-cli) (`az`)
- Policy assignment ที่ตรวจ tag อยู่แล้ว จาก repository [azure-policy-rg-vm-tag-governance](https://github.com/kamonphank/azure-policy-rg-vm-tag-governance) โดยชื่อต้องตรงกับ `PolicyAssignmentName`
- สิทธิ์ของผู้ deploy ตามตารางต่อไปนี้

| Task | Required permission |
|---|---|
| สร้าง Resource Group ใหม่ | Contributor ระดับ subscription |
| สร้าง resource ใน Resource Group | Contributor บน Resource Group นั้น |
| มอบสิทธิ์ Reader ให้ Function | Owner หรือ User Access Administrator ที่ subscription |

หากไม่มีสิทธิ์ข้อสุดท้าย ให้กำหนด `AssignSubscriptionReader = $false` และให้ administrator มอบสิทธิ์ตามหัวข้อ [Assigning the Reader role](#6-assigning-the-reader-role)

## 3. Deployment steps

หลัง clone repository ต้องแก้ config เพียง 4 ค่า (และ tag ของ Resource Group หากยังไม่มี) ค่าอื่นมีค่าเริ่มต้นที่ใช้ได้ทันที ไฟล์ตัวอย่างแสดงค่าที่ไม่บังคับเป็นคอมเมนต์ไว้ด้านล่าง

```powershell
Copy-Item config/deploy.config.example.psd1 config/deploy.config.psd1
```

```powershell
@{
    SubscriptionId = '<subscription-id>'
    ResourceGroup  = '<resource-group>'
    Location       = 'southeastasia'
    MailTo         = @('<responsible-person-email>', '<deployer-email>')
}
```

จากนั้นรันตามลำดับดังนี้

| Step | Command | Reason |
|---|---|---|
| 1 | `az login` | สคริปต์ใช้สิทธิ์ของ session นี้ในการสร้าง resource |
| 2 | `az account set --subscription <subscription-id>` | สคริปต์เทียบ subscription ที่ใช้งานอยู่กับ `SubscriptionId` และหยุดหากไม่ตรง เพื่อป้องกัน deploy ผิด subscription |
| 3 | `./scripts/deploy.ps1 -PlanOnly` | ตรวจสอบ config และแสดงว่า Resource Group มีอยู่แล้วหรือไม่ โดยไม่เปลี่ยนแปลงสิ่งใด |
| 4 | `./scripts/deploy.ps1` | deploy จริง โดยสคริปต์ถามยืนยันก่อนทุกครั้ง |

ไฟล์ `config/deploy.config.psd1` ถูกกำหนดใน `.gitignore` จึงไม่ถูก push ขึ้น repository ห้ามแก้ไขไฟล์ตัวอย่างให้เป็นค่าจริง

**การจัดการ Resource Group** สคริปต์ตรวจสอบก่อนทุกครั้ง

- หากมีอยู่แล้ว สคริปต์แสดงรายการ resource ที่มีในนั้น และให้พิมพ์ **ชื่อ Resource Group** เพื่อยืนยันก่อน deploy เพิ่มเติม โดยไม่แก้ไข resource เดิม รวมถึง tag และ region ของ Resource Group
- `ResourceGroupTags` มีผลเฉพาะ Resource Group ที่สคริปต์สร้างใหม่ หาก Resource Group มีอยู่แล้ว สคริปต์แจ้งเตือนว่าไม่นำ tag ใน config ไปใช้ และ tag เดิมไม่เปลี่ยน ส่วน resource ที่ระบบนี้สร้าง (Storage, Function App ฯลฯ) ไม่ได้กำหนด tag ให้ หาก Policy อื่นขององค์กรบังคับ tag บน resource เหล่านี้ ให้เพิ่ม tag เองภายหลัง
- หากยังไม่มี สคริปต์แจ้งว่าจะสร้างใหม่พร้อม region และ tag แล้วให้พิมพ์ `yes` เพื่อยืนยัน
- หากตอบไม่ตรง สคริปต์ยกเลิกโดยไม่มีสิ่งใดเปลี่ยนแปลง

| Option | Description |
|---|---|
| `-ConfigPath <path>` | ใช้ไฟล์ config อื่น เช่น `lab.psd1` และ `prod.psd1` (ไฟล์ `config/*.psd1` ยกเว้น `*.example.psd1` ถูกกำหนดใน `.gitignore`) |
| `-PlanOnly` | แสดงสรุป และรัน `what-if` หาก Resource Group มีอยู่แล้ว โดยไม่เปลี่ยนแปลงสิ่งใด |
| `-Yes` | ข้ามขั้นตอนการยืนยัน เหมาะกับการรันอัตโนมัติ |
| `-Part Infra` | deploy เฉพาะโครงสร้างและ App settings ใช้หลังแก้ไข config |
| `-Part Code` | ส่งเฉพาะโค้ด Function ใช้หลังแก้ไขโค้ดหรือ `holidays.json` |
| `-Set @{ Key = Value }` | กำหนดหรือทับค่าใน config จากบรรทัดคำสั่ง ใช้ key ชุดเดียวกับหัวข้อ 4 และตรวจสอบเหมือนค่าในไฟล์ ค่านี้ไม่ถูกบันทึกลงไฟล์ และสคริปต์แสดง key ที่ถูกทับในสรุปก่อนยืนยัน หากไม่มีไฟล์ config จะใช้ค่าจาก `-Set` ทั้งหมด |

### Production example

ระบบส่งอีเมลสองระดับ โดยตั้งค่าและ deploy เพียงครั้งเดียว ไม่ต้อง deploy ซ้ำเมื่อถึงรอบที่สอง

| Round | เงื่อนไข | To | Cc |
|---|---|---|---|
| 1 | อีเมลสรุปรายสัปดาห์ทุกฉบับ | `MailTo` (2 คน) | `MailCc` (1 คน) |
| 2 | มีรายการค้างเข้า Stage 2 ในสัปดาห์นั้น | `MailTo` (2 คน) | `MailCc` และ `MailCcEscalation` (2 คน) |

สร้างไฟล์ `config/prod.psd1` (ถูก `.gitignore` กันไว้เช่นเดียวกับ `deploy.config.psd1`) ดังนี้

```powershell
@{
    SubscriptionId    = '<subscription-id>'
    ResourceGroup     = '<resource-group>'
    Location          = 'southeastasia'
    ResourceGroupTags = @{ '<tag-name>' = '<value>' }   # ตามที่ Policy บังคับ
    MailTo            = @('<responsible-person-email>', '<deployer-email>')
    MailCc            = @('<manager-email>')
    MailCcEscalation  = @('<senior-manager-email>')
    MailEnabled       = $false    # เปลี่ยนเป็น $true เมื่อพร้อมส่งอีเมลจริง
}
```

```powershell
az login
az account set --subscription <subscription-id>

./scripts/deploy.ps1 -ConfigPath ./config/prod.psd1 -PlanOnly    # ตรวจสอบก่อน
./scripts/deploy.ps1 -ConfigPath ./config/prod.psd1              # deploy (ยังไม่ส่งอีเมล)

# อย่างน้อย 1 สัปดาห์ต่อมา เมื่อพร้อมส่งอีเมลจริง ให้แก้ MailEnabled = $true ใน prod.psd1 แล้วรัน
./scripts/deploy.ps1 -ConfigPath ./config/prod.psd1 -Part Infra
```

### Using -Set

ค่าที่ต้องคงอยู่ในระบบจริง (ผู้รับอีเมล, `MailEnabled`) ควรอยู่ในไฟล์ config เพราะ `-Set` ไม่ถูกบันทึก หากรัน `-Part Infra` ครั้งถัดไปโดยไม่ระบุ ค่าจะกลับไปเป็นค่าในไฟล์ `-Set` เหมาะกับค่าที่เปลี่ยนเป็นครั้งคราว ดังตัวอย่างต่อไปนี้

```powershell
# ใช้ config เดียวกัน แต่ทดสอบใน Resource Group อื่น โดยไม่ Cc ผู้จัดการ
./scripts/deploy.ps1 -ConfigPath ./config/prod.psd1 -Set @{ ResourceGroup = '<lab-resource-group>'; MailCc = @(); MailCcEscalation = @() }

# ไม่ใช้ไฟล์ config เลย
./scripts/deploy.ps1 -Set @{ SubscriptionId = '<subscription-id>'; ResourceGroup = '<resource-group>'; Location = 'southeastasia'; MailTo = '<deployer-email>' }
```

## 4. Configuration

config เป็น PowerShell data file (`.psd1`) ซึ่งเป็นข้อมูลล้วน สคริปต์ไม่รันโค้ดใดในไฟล์ คำอธิบายเบื้องต้นของแต่ละค่าอยู่ในคอมเมนต์ของ `config/deploy.config.example.psd1` สคริปต์ตรวจสอบค่าก่อนทำงาน และหยุดพร้อมแจ้งจุดที่ผิด เช่น key ที่ไม่รู้จัก GUID ไม่ถูกต้อง หรืออีเมลที่ยังเป็น `example.com`

| Config key | Required | Default | Description | App setting |
|---|---|---|---|---|
| `SubscriptionId` | Yes | - | subscription ที่ deploy ลง และเป็น subscription ที่ Function ได้รับสิทธิ์ Reader สคริปต์หยุดหากไม่ตรงกับ `az login` | - |
| `ResourceGroup` | Yes | - | ชื่อ Resource Group (มีแล้วจะ deploy เพิ่ม ยังไม่มีจะสร้างใหม่) | - |
| `Location` | Yes | - | region ของ Resource Group ใหม่ เช่น `southeastasia` (Resource Group เดิมใช้ region เดิม) | - |
| `ResourceGroupTags` | No | `@{}` | tag ของ Resource Group ที่สร้างใหม่เท่านั้น (ไม่มีผลกับ Resource Group ที่มีอยู่แล้ว) ควรครบตามที่ Policy บังคับ เพราะ Resource Group นี้ถูกตรวจด้วย | - |
| `NamePrefix` | No | `tagGov` | คำนำหน้าชื่อ resource (ตัวอักษรหรือตัวเลข 1 ถึง 8 ตัว) | - |
| `PolicyAssignmentName` | No | `rg-tag-governance-audit` | ชื่อ Policy assignment (ไม่ใช่ ID เต็ม) ตรวจสอบได้ด้วย `az policy assignment list --query "[].name" -o tsv` | `TG_ASSIGNMENT_NAME` |
| `ScanSubscriptionIds` | No | `@()` | จำกัด subscription ที่ scan ว่างคือทุก subscription ที่ Function อ่านได้ | `TG_SUBSCRIPTION_IDS` |
| `RgNameRegex` | No | ว่าง | กรองเฉพาะ Resource Group ที่ชื่อตรง regex (VM ใช้ชื่อ Resource Group ของตน) | `TG_RG_NAME_REGEX` |
| `SlaDays` | No | `14` | จำนวนวันที่ค้างก่อนเข้าสู่ Stage 1 | `TG_SLA_DAYS` |
| `MailEnabled` | No | `$false` | `$false` คือไม่ส่งอีเมล (เก็บเฉพาะ snapshot และ state) | `TG_MAIL_ENABLED` |
| `MailTo` | Yes | - | ผู้รับหลักของอีเมลสรุปทุกฉบับ ต้องเป็นอีเมลจริง | `TG_MAIL_TO` |
| `MailCc` | No | `@()` | Cc ของอีเมลสรุปทุกฉบับ | `TG_MAIL_CC` |
| `MailCcEscalation` | No | `@()` | Cc เพิ่มเติมเฉพาะอีเมลที่มีรายการ Stage 2 | `TG_MAIL_CC_ESCALATION` |
| `CreateAcsEmail` | No | `$true` | `$true` คือสร้าง ACS Email ใหม่ (ผู้ส่งเป็น `DoNotReply@<domain>.azurecomm.net`) `$false` คือใช้ ACS เดิม | `TG_MAIL_SENDER`, `TG_ACS_CONNECTION_STRING` |
| `ExistingAcsSender` | เมื่อ `CreateAcsEmail = $false` | ว่าง | ที่อยู่ผู้ส่งของ ACS เดิม | `TG_MAIL_SENDER` |
| `AssignSubscriptionReader` | No | `$true` | ให้สคริปต์มอบสิทธิ์ Reader แก่ Function | - |
| `EnableTestEndpoint` | No | `$false` | เปิด endpoint `/api/run` สำหรับทดสอบ | `TG_HTTP_ENABLED` |

ข้อควรทราบ

- **`MailEnabled = $false`** ระบบไม่บันทึกว่ารายการถูก escalate เมื่อเปิดส่งอีเมลภายหลัง รายการที่ค้างนานจะเริ่มที่ Stage 1 เสมอ ไม่ข้ามไป Stage 2 จึงแนะนำให้เริ่มด้วย `$false` อย่างน้อย 1 สัปดาห์เพื่อเก็บข้อมูล age
- **Cc** หากอีเมลใน `MailCc` และ `MailCcEscalation` ซ้ำกัน ระบบใส่เพียงครั้งเดียว
- **สิทธิ์ Reader** สคริปต์มอบให้เฉพาะ subscription ใน `SubscriptionId` หากต้องการ scan subscription อื่น administrator ต้องมอบสิทธิ์ให้เองตามหัวข้อ 6
- **`RgNameRegex`** โดยปกติไม่จำเป็นต้องใช้ เพราะ Policy ไม่นับ managed Resource Group (เช่น ของ Databricks) อยู่แล้ว หากใช้ ให้ทดสอบด้วย dry run และเทียบจำนวนกับหน้า Policy compliance เนื่องจาก regex ที่กว้างหรือแคบเกินไปทำให้ Resource Group หายจากรายงานโดยไม่มีผู้ทราบ
- **`EnableTestEndpoint`** ปิดไว้เป็นค่าเริ่มต้น เพราะ `dry_run=0` ส่งอีเมลและบันทึก state ได้จริง

## 5. Environment variables

ผู้ใช้ต้องตั้งตัวแปรเพียงตัวเดียว และเฉพาะเมื่อ `CreateAcsEmail = $false`

```powershell
$env:TG_ACS_CONNECTION_STRING = 'endpoint=https://<name>.communication.azure.com/;accesskey=<key>'
./scripts/deploy.ps1
```

ตัวแปรนี้มีผลเฉพาะในหน้าต่าง PowerShell นั้น ค่าถูกส่งให้ Bicep ผ่านไฟล์ parameter ชั่วคราวที่สคริปต์ลบเมื่อเสร็จ และไม่ปรากฏในบรรทัดคำสั่ง ห้ามระบุข้อมูลลับในไฟล์ config

App settings ของ Function (คอลัมน์ App setting ในตารางหัวข้อ 4) สคริปต์กำหนดให้จาก config โดยอัตโนมัติ หากต้องการเปลี่ยนค่า ให้แก้ไข config แล้วรัน `-Part Infra` ส่วน `TG_WORKBOOK_URL` สร้างให้ตอน deploy

## 6. Assigning the Reader role

ใช้เมื่อกำหนด `AssignSubscriptionReader = $false` หรือต้องการให้ Function scan subscription อื่น (สคริปต์แสดงคำสั่งนี้ไว้ท้ายการ deploy) ให้ administrator ที่มีสิทธิ์ Owner หรือ User Access Administrator ดำเนินการ

```powershell
$principalId = az functionapp identity show -g <resource-group> -n <function-app> --query principalId -o tsv
az role assignment create --assignee-object-id $principalId --assignee-principal-type ServicePrincipal --role Reader --scope /subscriptions/<subscription-id>
```

หากยังไม่มีสิทธิ์ Reader Function จะอ่าน Resource Graph ไม่ได้และได้ผลลัพธ์ว่าง

## 7. Post-deployment testing

1. **Workbook** เปิด Azure Portal ไปที่ Monitor, Workbooks, Shared แล้วเลือก "Tag Governance" และเทียบตัวเลขกับหน้า Policy compliance
2. **Dry run** เปิด endpoint ทดสอบชั่วคราว แล้วเรียกโดยไม่ส่งอีเมลและไม่บันทึก state

```powershell
az functionapp config appsettings set -g <rg> -n <function-app> --settings TG_HTTP_ENABLED=true -o none
$key = az functionapp function keys list -g <rg> -n <function-app> --function-name run_now --query default -o tsv
curl "https://<function-app>.azurewebsites.net/api/run?code=$key&dry_run=1&force=1"
```

| Parameter | Description |
|---|---|
| `dry_run` | `1` คือไม่ส่งอีเมลและไม่บันทึก state (ค่าเริ่มต้น) `0` คือทำงานจริง |
| `force` | `1` คือข้ามการตรวจสอบว่าวันนี้เป็นวันส่งหรือไม่ |
| `today` | วันที่ `YYYY-MM-DD` ใช้จำลองวัน เช่น +14 และ +21 วันเพื่อดู Stage 1 และ Stage 2 |

3. **ส่งอีเมลจริงหนึ่งครั้ง** หลังตั้ง `MailEnabled = $true` และ deploy ด้วย `-Part Infra` ให้เรียก `dry_run=0&force=1` แล้วตรวจสอบว่าอีเมลถึงผู้รับ และมี `state.json` กับ `snapshots/<date>.json` ใน Blob container `tag-governance`
4. **ปิด endpoint ทดสอบกลับ** ด้วย `TG_HTTP_ENABLED=false` ในคำสั่ง `appsettings set` ข้างต้น

ห้ามใช้ `dry_run=0` ร่วมกับ `today` ที่เป็นวันในอนาคต เพราะจะบันทึก state ที่ไม่ตรงกับความเป็นจริง

## 8. Rollout, update and removal

**Rollout แบบเป็นระยะ**

1. ตั้ง `MailEnabled = $false` และ deploy ระบบเริ่มเก็บ age ควรทำก่อนวันส่งอีเมลฉบับแรกอย่างน้อย 1 สัปดาห์ หากช้ากว่านั้น ให้เรียก `run?dry_run=0&force=1` หนึ่งครั้งเพื่อเริ่มเก็บ snapshot
2. เปลี่ยนเป็น `MailEnabled = $true` แล้วรัน `-Part Infra` โดยตั้ง `MailTo`, `MailCc` และ `MailCcEscalation` ไว้ตั้งแต่ต้นได้ เพราะ `MailCcEscalation` มีผลเฉพาะอีเมลที่มีรายการ Stage 2 เท่านั้น

**Update** แก้ไขโค้ดหรือ `holidays.json` ด้วย `-Part Code` และแก้ไข config ด้วย `-Part Infra`

**Removal** หาก Resource Group สร้างเพื่อระบบนี้โดยเฉพาะ ใช้ `az group delete -n <resource-group>` หากใช้ร่วมกับงานอื่น ให้ลบ resource ที่ขึ้นต้นด้วย `NamePrefix` ทีละรายการ และเพิกถอนสิทธิ์ Reader ด้วย `az role assignment delete --assignee <principalId> --role Reader --scope /subscriptions/<subscription-id>`

**Checklist ก่อนใช้งานจริง**

- [ ] ทดสอบใน lab ครบตามหัวข้อ 7 และได้รับอนุมัติตามขั้นตอนขององค์กร
- [ ] ยืนยันสถานะของ ACS Email ที่ https://aka.ms/acs-retirement และขอให้ผู้ดูแลอีเมลอนุญาตผู้ส่งจาก `azurecomm.net` (อีเมลมักมี banner "external sender" และอาจเข้า Junk)
- [ ] ตรวจสอบ `function/holidays.json` กับปฏิทินขององค์กร
- [ ] กำหนดผู้ดูแล Function ภายหลังสิ้นสุดโครงการ
- [ ] จำกัดผู้มีสิทธิ์ Contributor บน Resource Group เพราะ storage key และ ACS connection string อยู่ใน App settings

## 9. Troubleshooting

| Symptom | Cause and resolution |
|---|---|
| สคริปต์แจ้งว่า `az login` อยู่คนละ subscription | ใช้ `az account set --subscription <id>` |
| `AuthorizationFailed` ขณะมอบสิทธิ์ Reader | ไม่มีสิทธิ์ Owner หรือ User Access Administrator ให้ตั้ง `AssignSubscriptionReader = $false` และมอบสิทธิ์ตามหัวข้อ 6 |
| ชื่อ resource ซ้ำ | เปลี่ยน `NamePrefix` |
| Function ได้ผลลัพธ์ว่าง | ตรวจสอบว่ามีสิทธิ์ Reader, `PolicyAssignmentName` ตรงกับ assignment และ Policy ประเมินเสร็จแล้ว (ใช้ `az policy state trigger-scan` ได้) |
| ไม่ได้รับอีเมล | `MailEnabled` ยังเป็น `$false` อีเมลอยู่ใน Junk หรือทุกรายการผ่านแล้ว (ระบบไม่ส่งอีเมลเมื่อไม่มีรายการค้าง) |
| `/api/run` ตอบ 404 | `EnableTestEndpoint` ยังเป็น `$false` ดูหัวข้อ 7 |

## 10. For developers

repository นี้เป็น public ก่อน commit และ push ทุกครั้งควรตรวจสอบด้วยตนเองว่าไม่มีข้อมูลจริง เช่น subscription ID, อีเมล, ชื่อบริษัท หรือชื่อระบบภายใน ปะปนอยู่ ด้วย `git status` และ `git diff --staged` ไฟล์ config จริงและไฟล์ข้อมูล (`*.csv`, `*.xlsx`, `state.json`) ถูกกำหนดใน `.gitignore` แล้ว ควรเปิด Secret scanning และ Push protection ใน GitHub ด้วย ซึ่งตรวจจับ key และ token ได้ แต่ไม่ครอบคลุม ID อีเมล และชื่อบริษัท

- **รัน test suite** (ไม่ต้องใช้ Azure) ด้วย `pip install -r function/requirements.txt pytest` แล้ว `python -m pytest tests -q`
- **รัน Function ในเครื่อง** คัดลอก `function/local.settings.sample.json` เป็น `function/local.settings.json` (ไม่ถูก push) ระบุค่า `TG_*` ตามตารางหัวข้อ 4 แล้วรัน `func start`
- **กรณีเผลอ push ข้อมูลจริง** ให้ถือว่าข้อมูลรั่วไหลแล้ว เปลี่ยนค่า key ที่เกี่ยวข้องทันที แจ้งทีม security ล้างประวัติด้วย `git filter-repo` (หรือสร้าง repository ใหม่จากโค้ดที่สะอาด) แล้ว force-push