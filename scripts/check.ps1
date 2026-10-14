<#
.SYNOPSIS
  ตรวจว่าระบบที่ deploy แล้วพร้อมใช้/พร้อมโชว์หรือยัง (อ่านอย่างเดียว ไม่ส่งเมล ไม่บันทึก state)

.DESCRIPTION
  ตรวจ 5 จุด: Function ทำงานอยู่ / อ่าน secret จาก Key Vault ได้ / มีสิทธิ์ Reader / มี Workbook / รัน dry-run ได้
  จุดสุดท้ายต้องเปิด EnableTestEndpoint = $true ใน config (ชุด lab เปิดไว้แล้ว)

.PARAMETER ShowEmail  แสดงตัวอย่างอีเมลที่ระบบจะส่ง (เหมาะกับตอนนำเสนอ)
.EXAMPLE
  ./scripts/check.ps1
  ./scripts/check.ps1 -ShowEmail
#>
[CmdletBinding()]
param(
  [string]$ConfigPath = (Join-Path (Split-Path -Parent $PSScriptRoot) 'config/deploy.config.psd1'),
  [switch]$ShowEmail,
  [hashtable]$Set = @{}
)
$ErrorActionPreference = 'Stop'

$cfg = @{}
if (Test-Path $ConfigPath) { $cfg = Import-PowerShellDataFile -Path $ConfigPath }
elseif ($Set.Count -eq 0) { Write-Host "ไม่พบ config: $ConfigPath" -ForegroundColor Red; exit 1 }
foreach ($k in $Set.Keys) { $cfg[$k] = $Set[$k] }
$sub = "$($cfg.SubscriptionId)"; $rg = "$($cfg.ResourceGroup)"
$prefix = if ($cfg.NamePrefix) { "$($cfg.NamePrefix)" } else { 'tagGov' }

$script:fails = 0
function Pass($m) { Write-Host "  [PASS] $m" -ForegroundColor Green }
function Bad($m, $hint) { $script:fails++; Write-Host "  [FAIL] $m" -ForegroundColor Red; if ($hint) { Write-Host "         -> $hint" } }

$acct = (& az account show -o json 2>$null) | ConvertFrom-Json
if (-not $acct) { Write-Host 'ยังไม่ได้ az login' -ForegroundColor Red; exit 1 }
if ($acct.id -ne $sub) { Write-Host "az login อยู่คนละ subscription (az account set --subscription $sub)" -ForegroundColor Red; exit 1 }

Write-Host "`nตรวจ RG '$rg'" -ForegroundColor Cyan
$fn = & az functionapp list --resource-group $rg --query "[?starts_with(name,'$prefix-func-')].name | [0]" -o tsv 2>$null
if (-not $fn) { Bad 'ไม่พบ Function App' 'ยังไม่ได้ deploy? รัน ./scripts/deploy.ps1'; exit 1 }

# 1) Function ทำงานอยู่
$state = & az functionapp show -g $rg -n $fn --query state -o tsv
if ($state -eq 'Running') { Pass "Function App $fn กำลังทำงาน" } else { Bad "Function App สถานะ $state" 'ลองรีสตาร์ต: az functionapp restart' }

# 2) Key Vault reference อ่านได้
$ref = & az rest --method get --uri "https://management.azure.com/subscriptions/$sub/resourceGroups/$rg/providers/Microsoft.Web/sites/$fn/config/configreferences/appsettings?api-version=2022-03-01" --query "value[?name=='TG_ACS_CONNECTION_STRING'].properties.status | [0]" -o tsv 2>$null
if ($ref -eq 'Resolved') { Pass 'อ่าน ACS secret จาก Key Vault ได้' }
else { Bad "อ่าน secret จาก Key Vault ไม่ได้ (สถานะ: $(if ($ref) { $ref } else { 'ไม่ทราบ' }))" "รอ 2-3 นาทีให้สิทธิ์แพร่กระจาย แล้วรีสตาร์ต: az functionapp restart -g $rg -n $fn" }

# 3) สิทธิ์ Reader
$principal = & az functionapp identity show -g $rg -n $fn --query principalId -o tsv
$readers = & az role assignment list --assignee $principal --role Reader --scope "/subscriptions/$sub" --query "length(@)" -o tsv 2>$null
if ([int]$readers -ge 1) { Pass 'Function มีสิทธิ์ Reader ที่ subscription' }
else { Bad 'Function ยังไม่มีสิทธิ์ Reader (จะอ่าน Resource Graph ไม่ได้)' "ให้ admin รัน: az role assignment create --assignee-object-id $principal --assignee-principal-type ServicePrincipal --role Reader --scope /subscriptions/$sub" }

# 4) Workbook
$wb = & az resource list -g $rg --resource-type Microsoft.Insights/workbooks --query "length(@)" -o tsv
if ([int]$wb -ge 1) { Pass 'มี Workbook (Azure Portal > Monitor > Workbooks > Shared)' } else { Bad 'ไม่พบ Workbook' 'รัน deploy.ps1 -Part Infra' }

# 5) dry-run
$enabled = & az functionapp config appsettings list -g $rg -n $fn --query "[?name=='TG_HTTP_ENABLED'].value | [0]" -o tsv
if ($enabled -ne 'true') { Bad 'ข้าม dry-run: endpoint ทดสอบปิดอยู่' 'ตั้ง EnableTestEndpoint = $true ใน config แล้ว ./scripts/deploy.ps1 -Part Infra' }
else {
  try {
    $key = & az functionapp function keys list -g $rg -n $fn --function-name run_now --query default -o tsv
    $r = Invoke-RestMethod "https://$fn.azurewebsites.net/api/run?code=$key&dry_run=1&force=1" -TimeoutSec 120
    if ($r.status -eq 'ok') {
      $s = $r.summary
      Pass "dry-run สำเร็จ: ค้าง $($s.total) รายการ (ใหม่ $($s.new), แก้แล้ว $($s.resolved), เกิน SLA $($s.stage1 + $s.stage2))"
      if ($ShowEmail) {
        Write-Host "`n--- ตัวอย่างอีเมลที่ระบบจะส่ง ---" -ForegroundColor Cyan
        if ($r.email.subject) { Write-Host "To: $($r.email.to -join ', ')`nSubject: $($r.email.subject)`n"; Write-Host $r.email.text_preview } else { Write-Host $r.email }
      }
    } else { Bad "dry-run ตอบ status = $($r.status)" 'ดู log ที่ Application Insights' }
  } catch { Bad "dry-run ล้มเหลว: $($_.Exception.Message)" 'ถ้า 500: มักเป็นสิทธิ์ Reader หรืออ่าน secret ไม่ได้ (ดูข้อ 2-3) รอแล้วลองใหม่ หรือดู log ที่ Application Insights' }
}

Write-Host ''
if ($script:fails -eq 0) { Write-Host 'พร้อมโชว์ ✔' -ForegroundColor Green } else { Write-Host "ยังไม่พร้อม: $($script:fails) จุด (ดู [FAIL] ด้านบน)" -ForegroundColor Red; exit 1 }
