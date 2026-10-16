# ตัวอย่าง config สำหรับ scripts/deploy.ps1 (รายละเอียดทุกค่าอยู่ใน docs/DEPLOY.md หัวข้อ Configuration)
#
#   1) Copy-Item config/deploy.config.example.psd1 config/deploy.config.psd1
#   2) แก้เฉพาะส่วน REQUIRED (4 ค่า และ tag หาก RG ยังไม่มี) ก็ deploy ได้ (ไฟล์จริงถูก .gitignore กันไว้ ห้ามแก้ไฟล์ example ใส่ค่าจริง)
#   3) ห้ามใส่ความลับ (connection string, key, password) ในไฟล์นี้
@{
    # ===== REQUIRED =====
    SubscriptionId = '00000000-0000-0000-0000-000000000000'    # ต้องตรงกับ subscription ที่ az login อยู่
    ResourceGroup  = 'rg-tag-governance'                       # มีอยู่แล้ว = deploy เพิ่ม / ยังไม่มี = สร้างใหม่ (สคริปต์ถามยืนยันทั้งสองกรณี)
    Location       = 'southeastasia'                           # region ของ RG ใหม่
    MailTo         = @('responsible.person@example.com', 'deployer@example.com')   # ผู้รับ (To) ต้องเป็นอีเมลจริง

    # tag ที่ใส่ให้ RG ใหม่และทุก resource ของโปรเจกต์ ควรครบตามที่ Policy บังคับ (RG ที่มีอยู่แล้วไม่ถูกแก้ tag)
    Tags = @{
        # owner = '...' ; department = '...' ; environment = '...' ; project = '...'
    }

    # ===== OPTIONAL (ลบเครื่องหมาย # ออกเมื่อต้องการเปลี่ยน ค่าที่แสดงคือค่าเริ่มต้น) =====
    # MailEnabled              = $false   # $false = เก็บ snapshot อย่างเดียว ยังไม่ส่งอีเมล
    # MailCc                   = @()      # Cc ทุกฉบับ
    # MailCcEscalation         = @()      # Cc เพิ่มเฉพาะอีเมลที่มีรายการ Stage 2
    # SlaDays                  = 14       # จำนวนวันที่ค้างก่อนเข้า Stage 1
    # NamePrefix               = 'tagGov' # คำนำหน้าชื่อ resource (1-8 ตัวอักษร/ตัวเลข)
    # PolicyAssignmentName     = 'rg-tag-governance-audit'
    # ScanSubscriptionIds      = @()      # ว่าง = ทุก subscription ที่ Function อ่านได้
    # RgNameRegex              = ''       # โดยปกติไม่ต้องใช้
    # CreateAcsEmail           = $true    # $false = ใช้ ACS เดิม ต้องมี ExistingAcsSender และ env TG_ACS_CONNECTION_STRING
    # ExistingAcsSender        = ''
    # AssignSubscriptionReader = $true    # $false = admin มอบสิทธิ์ Reader เอง
    # EnableTestEndpoint       = $false    # เปิดเฉพาะตอนทดสอบ
    # EnableManualSend         = $false    # $true = เปิด POST /api/send ส่งเมลทันทีตอนไหนก็ได้
}