# Quickstart (MVP / เดโม่)

ต้องมี PowerShell, Azure CLI (`az login` แล้ว) และสิทธิ์ Owner / User Access Administrator ที่ subscription
(ถ้าไม่มี ใส่ `AssignSubscriptionReader = $false` แล้วให้ admin มอบสิทธิ์ Reader ทีหลัง ดู DEPLOY.md หัวข้อ 6)

## เตรียมครั้งเดียว
```powershell
Copy-Item config/lab.example.psd1 config/deploy.config.psd1   # แก้ SubscriptionId และ MailTo (และ tag ถ้า Policy บังคับ)
```
ตั้งชื่อเป็น `deploy.config.psd1` คำสั่งด้านล่างจึงไม่ต้องระบุ `-ConfigPath`

## 3 คำสั่งที่ใช้
| ทำอะไร | คำสั่ง |
|---|---|
| **Deploy ทั้งชุด** | `./scripts/deploy.ps1 -Yes` |
| **เช็กว่าพร้อมโชว์หรือยัง** | `./scripts/check.ps1 -ShowEmail` |
| **Clean ทั้งชุด** | `./scripts/teardown.ps1 -Execute -Yes` |

- `check.ps1` ตรวจ 5 จุด (Function ทำงาน, อ่าน secret ได้, มีสิทธิ์ Reader, มี Workbook, dry-run ได้) แล้วตอบ `พร้อมโชว์ ✔` หรือบอกว่าจุดไหนไม่ผ่านพร้อมวิธีแก้ ส่วน `-ShowEmail` พิมพ์ตัวอย่างอีเมลที่ระบบจะส่ง ใช้โชว์พี่ได้เลย
- หลัง deploy ใหม่ รอ 2-3 นาทีก่อนรัน check เพราะสิทธิ์ต้องใช้เวลาแพร่กระจาย
- อยากดูก่อนว่า clean จะลบอะไร: `./scripts/teardown.ps1` (ไม่ใส่ `-Execute` = ดูเฉยๆ)

## เริ่มใหม่ทั้งชุดด้วยคำสั่งเดียว (state ไม่หาย)
```powershell
./scripts/teardown.ps1 -BackupTo ./backup -Execute -Yes; ./scripts/deploy.ps1 -RestoreFrom ./backup -Yes
```
สำรอง state -> ลบเฉพาะของโปรเจกต์นี้ -> purge ของที่ค้างใน soft-delete -> deploy ใหม่ -> คืน state (ไม่งั้นอายุของรายการเริ่มนับใหม่)

## ลำดับที่แนะนำก่อนเดโม่
1. `./scripts/teardown.ps1 -Execute -Yes` แล้ว `./scripts/deploy.ps1 -Yes` (ซ้อม deploy จากศูนย์ ใช้เวลาไม่กี่นาที)
2. รอ 2-3 นาที แล้ว `./scripts/check.ps1 -ShowEmail` ต้องได้ `พร้อมโชว์ ✔`
3. เปิด Workbook: Azure Portal > Monitor > Workbooks > Shared > "Tag Governance"

## ชุดสำหรับทีมใช้งานจริง (ตอนส่งมอบ)
```powershell
Copy-Item config/team.example.psd1 config/team.psd1   # แก้ SubscriptionId, MailTo, MailCcEscalation
./scripts/deploy.ps1 -ConfigPath ./config/team.psd1 -PlanOnly   # ดูก่อน
./scripts/deploy.ps1 -ConfigPath ./config/team.psd1             # deploy จริง (ถามยืนยัน)
```
ค่าเริ่มต้นปลอดภัย: ปิดการส่งเมล (เก็บ snapshot ก่อน 1 สัปดาห์) และปิด endpoint ทดสอบ พร้อมส่งจริงแก้ `MailEnabled = $true` แล้วรัน `-Part Infra`

ห้าม commit `config/*.psd1` ตัวจริงและโฟลเดอร์ `backup/` (ถูก .gitignore กันไว้แล้ว)
