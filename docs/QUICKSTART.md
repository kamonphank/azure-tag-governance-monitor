# Quickstart: 2 ชุดคำสั่ง

ต้องมี PowerShell, Azure CLI (`az login` แล้ว) และ Owner / User Access Administrator ที่ subscription
(ถ้าไม่มี ให้ใส่ `AssignSubscriptionReader = $false` ใน config แล้วให้ admin มอบสิทธิ์ Reader ทีหลัง ดู DEPLOY.md หัวข้อ 6)

## ชุดที่ 1: ห้องแล็บของตัวเอง ลบแล้ว deploy ใหม่ทั้งชุด

เตรียมครั้งเดียว:
```powershell
Copy-Item config/lab.example.psd1 config/lab.psd1     # แล้วแก้ SubscriptionId, MailTo (และ tag ถ้า Policy บังคับ)
```

คำสั่ง (ทุกครั้งที่อยากเริ่มใหม่):
```powershell
./scripts/teardown.ps1 -ConfigPath ./config/lab.psd1 -BackupTo ./backup -Execute -Yes; ./scripts/deploy.ps1 -ConfigPath ./config/lab.psd1 -RestoreFrom ./backup -Yes
```
สำรอง state -> ลบเฉพาะของโปรเจกต์นี้ -> purge ของที่ค้างใน soft-delete -> deploy ใหม่ -> คืน state
ครั้งแรกที่ยังไม่มีอะไรให้ลบ คำสั่งนี้ใช้ได้เหมือนกัน (ส่วนลบจะข้ามเอง)
อยากดูก่อนว่าจะลบอะไร: `./scripts/teardown.ps1 -ConfigPath ./config/lab.psd1`

ทดสอบหลัง deploy (ไม่ส่งเมล ไม่บันทึกอะไร):
```powershell
$rg='rg-tag-governance-lab'; $fn=az functionapp list -g $rg --query "[0].name" -o tsv
$key=az functionapp function keys list -g $rg -n $fn --function-name run_now --query default -o tsv
Invoke-RestMethod "https://$fn.azurewebsites.net/api/run?code=$key&dry_run=1&force=1" | ConvertTo-Json -Depth 6
```
ผลที่ถูก: ผลลัพธ์ที่มี `"status": "ok"` และ `summary` (จำนวนรายการ) ถ้าได้ 404 แปลว่า `EnableTestEndpoint` ยังไม่เป็น `$true`
ถ้าอ่าน TG_ACS_CONNECTION_STRING ไม่ได้ ดูที่ Portal: Function App > Environment variables ต้องขึ้นเครื่องหมายถูกสีเขียว (ถ้าแดง รอไม่กี่นาทีหรือรีสตาร์ต Function)

## ชุดที่ 2: ให้ทีมใช้งานจริง

เตรียมครั้งเดียว:
```powershell
Copy-Item config/team.example.psd1 config/team.psd1   # แก้ SubscriptionId, MailTo, MailCcEscalation
```

คำสั่ง:
```powershell
./scripts/deploy.ps1 -ConfigPath ./config/team.psd1 -PlanOnly   # ดูก่อน
./scripts/deploy.ps1 -ConfigPath ./config/team.psd1             # deploy จริง (ถามยืนยัน)
```
สัปดาห์แรก `MailEnabled = $false` ระบบเก็บ snapshot อย่างเดียว เมื่อพร้อมส่งเมลจริง แก้เป็น `$true` แล้วรัน
`./scripts/deploy.ps1 -ConfigPath ./config/team.psd1 -Part Infra`

ย้ายระบบไป RG/subscription ใหม่: ชุดที่ 1 ด้วย config ของตัวเอง (สำรองและคืน state ทำให้อายุของรายการนับต่อ)

ห้าม commit `config/*.psd1` ตัวจริงและโฟลเดอร์ `backup/` (ถูก .gitignore กันไว้แล้ว)
