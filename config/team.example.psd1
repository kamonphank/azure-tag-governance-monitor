# ชุดที่ 2: ให้ทีมใช้งานจริง Copy-Item config/team.example.psd1 config/team.psd1 แล้วแก้ค่าให้ครบ
@{
    SubscriptionId = '00000000-0000-0000-0000-000000000000'
    ResourceGroup  = 'rg-tag-governance'
    Location       = 'southeastasia'
    MailTo         = @('team-mailbox@yourcompany.com')      # กล่องเมลของทีม

    Tags = @{
        # ใส่ tag ที่ Policy ของคุณบังคับ (ใส่ให้ RG ที่สร้างใหม่และทุก resource)
    }

    MailCcEscalation   = @('manager@yourcompany.com')       # ผู้จัดการที่ถูก Cc เมื่อรายการค้างเลย 2 สัปดาห์
    MailEnabled        = $false   # สัปดาห์แรกเก็บ snapshot เฉยๆ พร้อมส่งจริงค่อยแก้เป็น $true แล้วรัน -Part Infra
    EnableTestEndpoint = $false   # ทีมใช้งานจริงต้องปิด
    SlaDays            = 14
}
