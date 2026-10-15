# ชุดที่ 1: ห้องแล็บของตัวเอง (ลบ/สร้างใหม่ได้บ่อย) Copy-Item config/lab.example.psd1 config/lab.psd1 แล้วแก้ 4 ค่าแรก
@{
    SubscriptionId = '00000000-0000-0000-0000-000000000000'
    ResourceGroup  = 'rg-tag-governance-lab'
    Location       = 'southeastasia'
    MailTo         = @('you@yourcompany.com')          # อีเมลจริงของคุณเอง

    ResourceGroupTags = @{
        # ใส่ tag ที่ Policy ของคุณบังคับ เพื่อให้ RG แล็บผ่านเอง
    }

    NamePrefix         = 'tgLab'
    MailEnabled        = $false   # เก็บ snapshot อย่างเดียว ยังไม่ส่งเมล (ทดสอบส่งเมลด้วย dry_run ก่อน)
    EnableTestEndpoint = $true    # เปิด /api/run ให้ทดสอบ (แล็บเท่านั้น)
    SlaDays            = 14
}
