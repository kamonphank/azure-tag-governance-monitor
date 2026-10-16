# ชุดที่ 2: ให้ทีมใช้งานจริง Copy-Item config/team.example.psd1 config/prod.psd1 แล้วแก้ค่าให้ครบ
# มีครบทุก key ที่ deploy.ps1 รู้จัก รายละเอียดแต่ละค่าอยู่ใน docs/DEPLOY.md หัวข้อ Configuration
# ห้ามใส่ความลับ (connection string, key, password) ในไฟล์นี้
@{
    # ===== ที่ต้องแก้ =====
    SubscriptionId = '00000000-0000-0000-0000-000000000000'   # ต้องตรงกับ subscription ที่ az login อยู่
    ResourceGroup  = 'rg-tag-governance'                      # มีอยู่แล้ว = deploy เพิ่ม / ยังไม่มี = สร้างใหม่
    Location       = 'southeastasia'                          # region ของ RG ใหม่

    Tags = @{
        # ใส่ tag ที่ Policy ของคุณบังคับ (ใส่ให้ RG ที่สร้างใหม่และทุก resource)
        # owner = '...' ; department = '...' ; environment = '...' ; project = '...'
    }

    # ===== อีเมล =====
    MailTo           = @('team-mailbox@yourcompany.com')      # ผู้รับหลัก (To) ทุกฉบับ
    MailCc           = @()                                    # Cc ทุกฉบับ
    MailCcEscalation = @('manager@yourcompany.com')           # Cc เพิ่มเฉพาะเมลที่มีรายการ Stage 2 (ค้างเกิน SLA และแจ้งไปแล้วรอบก่อน)
    MailEnabled      = $false                                 # สัปดาห์แรกเก็บ snapshot เฉยๆ พร้อมส่งจริงค่อยแก้เป็น $true แล้วรัน -Part Infra
    CreateAcsEmail   = $true                                  # $false = ใช้ ACS เดิม ต้องตั้ง ExistingAcsSender และ env TG_ACS_CONNECTION_STRING
    ExistingAcsSender = ''                                    # ใช้เมื่อ CreateAcsEmail = $false เช่น 'DoNotReply@<domain>.azurecomm.net'

    # ===== ขอบเขตการตรวจ =====
    PolicyAssignmentName = 'rg-tag-governance-audit'          # ชื่อ Policy assignment (ไม่ใช่ ID เต็ม)
    ScanSubscriptionIds  = @()                                # ว่าง = ทุก subscription ที่ Function อ่านได้
    RgNameRegex          = ''                                 # ว่าง = ไม่กรอง (โดยปกติไม่ต้องใช้)
    SlaDays              = 14                                 # จำนวนวันที่ค้างก่อนเข้า Stage 1

    # ===== ระบบ =====
    NamePrefix               = 'tagGov'                       # คำนำหน้าชื่อ resource (ตัวอักษร/ตัวเลข 1-8 ตัว)
    AssignSubscriptionReader = $true                          # ให้สคริปต์มอบสิทธิ์ Reader แก่ Function ที่ระดับ subscription
    EnableTestEndpoint       = $false                         # /api/run ปิดไว้ เปิดชั่วคราวด้วย -Set @{ EnableTestEndpoint = $true }
    EnableManualSend         = $false                         # $true = เปิด POST /api/send ส่งเมลทันทีตอนไหนก็ได้
}
