# Quickstart

ต้องมี PowerShell, Azure CLI (`az login` แล้ว) และสิทธิ์ Owner / User Access Administrator ที่ subscription
(ถ้าไม่มี ใส่ `AssignSubscriptionReader = $false` แล้วให้ admin มอบสิทธิ์ Reader ทีหลัง ดู DEPLOY.md หัวข้อ 3)

## เตรียมครั้งเดียว
```powershell
Copy-Item config/lab.example.psd1 config/deploy.config.psd1   # แก้ SubscriptionId และ MailTo
```

## 2 คำสั่ง
```powershell
./scripts/deploy.ps1 -Yes                       # deploy ทั้งชุด
./scripts/teardown.ps1 -Execute -Yes            # clean ทั้งชุด
```
- `teardown.ps1` ลบเฉพาะของที่โปรเจกต์นี้สร้าง และ purge Key Vault / Log Analytics ที่ค้างใน soft-delete เพื่อให้ deploy ใหม่ได้ ถ้าไม่ใส่ `-Execute` จะแสดงรายการที่จะลบเฉยๆ
- หลัง deploy รอ 2-3 นาทีก่อนตรวจ เพราะสิทธิ์ต้องใช้เวลาแพร่กระจาย

## อยากเก็บ state ข้ามการลบ (ไม่บังคับ)
```powershell
./scripts/teardown.ps1 -BackupTo ./backup -Execute -Yes
./scripts/deploy.ps1 -RestoreFrom ./backup -Yes
```
ไม่ทำก็ได้ แต่อายุของรายการที่ค้างจะเริ่มนับใหม่

## ส่งมอบให้ทีม
```powershell
Copy-Item config/team.example.psd1 config/team.psd1   # แก้ SubscriptionId, MailTo, MailCcEscalation
./scripts/deploy.ps1 -ConfigPath ./config/team.psd1
```
ค่าเริ่มต้นปิดการส่งเมลและปิด endpoint ทดสอบ พร้อมส่งจริงแก้ `MailEnabled = $true` แล้วรัน `-Part Infra`

ห้าม commit `config/*.psd1` ตัวจริงและโฟลเดอร์ `backup/` (ถูก .gitignore กันไว้แล้ว)
