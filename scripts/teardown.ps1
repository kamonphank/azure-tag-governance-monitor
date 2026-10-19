<#
.SYNOPSIS
  ลบ resource ที่ deploy.ps1 สร้างไว้ เพื่อเริ่มใหม่ (อ่านค่าจาก config เดียวกับ deploy.ps1)

.DESCRIPTION
  ลบ "เฉพาะ resource ที่ deployment ของโปรเจกต์นี้สร้าง" (ดูจากประวัติ deployment ชื่อ tag-governance-*)
  จึงไม่แตะ resource อื่นใน RG แม้ RG จะมีของอื่นอยู่ด้วย
  ลำดับ: [สำรอง state] -> เพิกถอนสิทธิ์ Reader -> ลบ resource -> purge Key Vault และ Log Analytics ที่ค้างอยู่ในสถานะ soft-delete
  (ถ้าไม่ purge การ deploy ใหม่ด้วยชื่อเดิมจะชน)
  ค่าเริ่มต้นแสดงรายการเฉยๆ ต้องใส่ -Execute จึงลบจริง และต้องพิมพ์ชื่อ RG ยืนยัน

.PARAMETER ConfigPath  ไฟล์ config (ค่าเริ่มต้น config/deploy.config.psd1) ใช้เฉพาะ SubscriptionId, ResourceGroup, NamePrefix
.PARAMETER Execute     ลบจริง (ถ้าไม่ใส่ = แสดงรายการที่จะลบเฉยๆ)
.PARAMETER BackupTo    โฟลเดอร์สำหรับสำรอง state.json และ snapshots ก่อนลบ (ใช้กับ deploy.ps1 -RestoreFrom เพื่อให้ age ของรายการไม่เริ่มนับใหม่)
.PARAMETER DeleteResourceGroup  ลบทั้ง RG ด้วย (ใช้เมื่อ RG สร้างมาเพื่อระบบนี้โดยเฉพาะ)
.PARAMETER Yes         ข้ามคำถามยืนยัน (ต้องใส่ -Execute ด้วย)
.PARAMETER Set         ทับค่า config เช่น -Set @{ ResourceGroup = 'rg-lab' }

.EXAMPLE
  ./scripts/teardown.ps1                                  # ดูว่าจะลบอะไร (ยังไม่ลบ)
  ./scripts/teardown.ps1 -BackupTo ./backup -Execute      # สำรอง state แล้วลบ
  ./scripts/deploy.ps1 -RestoreFrom ./backup              # deploy ใหม่ พร้อมคืน state
#>
[CmdletBinding()]
param(
  [string]$ConfigPath = (Join-Path (Split-Path -Parent $PSScriptRoot) 'config/deploy.config.psd1'),
  [switch]$Execute,
  [string]$BackupTo,
  [switch]$DeleteResourceGroup,
  [switch]$Yes,
  [hashtable]$Set = @{}
)
$ErrorActionPreference = 'Stop'

function Step($m) { Write-Host "`n==> $m" -ForegroundColor Cyan }
function Fail($m) { Write-Host "`nERROR: $m" -ForegroundColor Red; exit 1 }
function Info($m) { Write-Host "    $m" }
function Warn($m) { Write-Host "    ! $m" -ForegroundColor Yellow }

# ---------- config ----------
$cfg = @{}
if (Test-Path $ConfigPath) { $cfg = Import-PowerShellDataFile -Path $ConfigPath }
elseif ($Set.Count -eq 0) { Fail "ไม่พบไฟล์ config: $ConfigPath (หรือใช้ -Set)" }
foreach ($k in $Set.Keys) { $cfg[$k] = $Set[$k] }
$subId = "$($cfg.SubscriptionId)"
$rg = "$($cfg.ResourceGroup)"
$prefix = if ($cfg.NamePrefix) { "$($cfg.NamePrefix)" } else { 'tagGov' }
if ($subId -notmatch '^[0-9a-fA-F]{8}-([0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$') { Fail 'SubscriptionId ไม่ถูกต้อง' }
if (-not $rg) { Fail 'ต้องระบุ ResourceGroup' }
if ($Yes -and -not $Execute) { Fail '-Yes ใช้ร่วมกับ -Execute เท่านั้น' }

Step 'ตรวจ Azure CLI'
if (-not (Get-Command az -ErrorAction SilentlyContinue)) { Fail 'ไม่พบ Azure CLI (az)' }
$acct = (& az account show -o json 2>$null) | ConvertFrom-Json
if (-not $acct) { Fail 'ยังไม่ได้ login  รัน:  az login' }
if ($acct.id -ne $subId) { Fail "az login อยู่คนละ subscription  ตอนนี้: $($acct.id)  config: $subId  สลับด้วย: az account set --subscription $subId" }
if ((& az group exists --name $rg -o tsv) -ne 'true') { Info "ไม่พบ RG '$rg' ไม่มีอะไรต้องลบ"; exit 0 }

# ---------- หา resource ที่โปรเจกต์นี้สร้าง ----------
Step "หา resource ที่ deployment ของโปรเจกต์นี้สร้างใน '$rg'"
$deps = @(& az deployment group list --resource-group $rg --query "[?starts_with(name, 'tag-governance-')].name" -o tsv)   # ต้องมีช่องว่าง: PowerShell 5.1 จึงครอบด้วย " ไม่งั้น cmd.exe (az.cmd) อ่าน ( ) เองแล้ว error
if ($deps.Count -eq 0) { Fail "ไม่พบ deployment ชื่อ tag-governance-* ใน RG นี้ (ไม่ได้สร้างด้วย deploy.ps1 หรือประวัติถูกลบ) ผมจะไม่เดาว่าอะไรเป็นของโปรเจกต์ ให้ลบเองหรือใช้ -DeleteResourceGroup" }
$ids = @()
foreach ($d in $deps) {
  $ids += @(& az deployment group show --resource-group $rg --name $d --query "properties.outputResources[].id" -o tsv)
}
$ids = @($ids | Where-Object { $_ } | Sort-Object -Unique)

# ข้าม resource ลูกและ deployment (ถูกลบพร้อมตัวแม่) และจัดลำดับการลบ
function Skip($id) { $id -match '/providers/Microsoft\.Resources/deployments/' -or $id -match '/domains/' -or $id -match '/secrets/' -or $id -match '/storageAccounts/[^/]+/' -or $id -match '/providers/Microsoft\.Authorization/' }
function Rank($id) {
  switch -Regex ($id) {
    '/Microsoft\.Web/sites/' { 0; break }
    '/Microsoft\.Communication/communicationServices/' { 1; break }
    '/Microsoft\.Communication/emailServices/' { 2; break }
    '/Microsoft\.KeyVault/vaults/' { 8; break }
    default { 5 }
  }
}
$targets = @($ids | Where-Object { -not (Skip $_) } | Sort-Object { Rank $_ })
$kvIds = @($targets | Where-Object { $_ -match '/Microsoft\.KeyVault/vaults/' })
$lawIds = @($targets | Where-Object { $_ -match '/Microsoft\.OperationalInsights/workspaces/' })
$funcId = $targets | Where-Object { $_ -match '/Microsoft\.Web/sites/' } | Select-Object -First 1
$storageId = $targets | Where-Object { $_ -match '/Microsoft\.Storage/storageAccounts/' } | Select-Object -First 1

if ($DeleteResourceGroup) { Warn "จะลบทั้ง Resource Group '$rg' รวมของอื่นใน RG ด้วย" }
Info "resource ที่จะลบ ($($targets.Count)):"
$targets | ForEach-Object { Info "  - $($_ -replace '^.*/providers/','')" }
if ($funcId) { Info '  - สิทธิ์ Reader ระดับ subscription ของ Function (ถ้ามี)' }
if ($BackupTo) { Info "สำรอง state ไว้ที่: $BackupTo" } else { Warn 'ไม่ได้ใช้ -BackupTo: state.json (วันที่ตรวจพบครั้งแรก) จะหาย อายุของรายการจะเริ่มนับใหม่' }

if (-not $Execute) { Write-Host "`nนี่คือการดูเฉยๆ ยังไม่ได้ลบอะไร ใส่ -Execute เพื่อลบจริง" -ForegroundColor Green; exit 0 }
if (-not $Yes) {
  $ans = Read-Host "`nพิมพ์ชื่อ RG '$rg' เพื่อยืนยันการลบ (หรือ Enter เพื่อยกเลิก)"
  if ($ans -ne $rg) { Write-Host 'ยกเลิก ไม่มีอะไรถูกลบ'; exit 0 }
}

# ---------- สำรอง state ----------
if ($BackupTo) {
  if (-not $storageId) { Fail 'ไม่พบ Storage account ใน deployment จึงสำรองไม่ได้ (ยกเลิกก่อนลบ)' }
  Step "สำรอง state และ snapshots -> $BackupTo"
  $stName = $storageId.Split('/')[-1]
  New-Item -ItemType Directory -Force $BackupTo | Out-Null
  $env:AZURE_STORAGE_KEY = (& az storage account keys list --account-name $stName --resource-group $rg --query "[0].value" -o tsv)
  try {
    & az storage blob download-batch --account-name $stName --source tag-governance --destination $BackupTo --overwrite true -o none
    if ($LASTEXITCODE -ne 0) { Fail 'สำรองไม่สำเร็จ (ยกเลิกก่อนลบ ยังไม่มีอะไรถูกลบ)' }
  } finally { Remove-Item Env:\AZURE_STORAGE_KEY -ErrorAction SilentlyContinue }
  Info "สำรองแล้ว: $((Get-ChildItem $BackupTo -Recurse -File | Measure-Object).Count) ไฟล์"
}

# ---------- เพิกถอนสิทธิ์ Reader (ต้องทำก่อนลบ Function เพราะต้องใช้ principalId) ----------
if ($funcId) {
  $fn = $funcId.Split('/')[-1]
  $pid_ = & az functionapp identity show --resource-group $rg --name $fn --query principalId -o tsv 2>$null
  if ($pid_) {
    Step 'เพิกถอนสิทธิ์ Reader ของ Function'
    & az role assignment delete --assignee $pid_ --role Reader --scope "/subscriptions/$subId" 2>$null
    if ($LASTEXITCODE -ne 0) { Warn 'เพิกถอนไม่สำเร็จหรือไม่มีสิทธิ์นี้อยู่ (ตรวจเองภายหลังที่ Access control ของ subscription)' }
  }
}

# ---------- ลบ ----------
Step 'ลบ resource'
if ($DeleteResourceGroup) {
  & az group delete --name $rg --yes
  if ($LASTEXITCODE -ne 0) { Fail 'ลบ RG ไม่สำเร็จ' }
} else {
  $failed = @()
  foreach ($id in $targets) {
    Info "ลบ $($id -replace '^.*/providers/','')"
    if ($id -in $lawIds) { & az monitor log-analytics workspace delete --ids $id --force true --yes 2>$null }
    else { & az resource delete --ids $id 2>$null }
    if ($LASTEXITCODE -ne 0) { $failed += $id }
  }
  if ($failed.Count) { Warn "ลบไม่สำเร็จ $($failed.Count) รายการ (อาจเพราะลำดับ ลองรันใหม่อีกครั้ง):"; $failed | ForEach-Object { Info "  - $_" } }
}

# ---------- purge ของที่ค้างใน soft-delete ----------
foreach ($id in $kvIds) {
  $kv = $id.Split('/')[-1]
  Step "purge Key Vault $kv (soft-delete)"
  $loc = & az keyvault list-deleted --query "[?name=='$kv'].properties.location | [0]" -o tsv
  if ($loc) {
    & az keyvault purge --name $kv --location $loc
    if ($LASTEXITCODE -ne 0) { Warn "purge ไม่สำเร็จ (ถ้าเปิด purge protection จะ purge ไม่ได้ ต้องรอครบกำหนดหรือใช้ชื่ออื่น: เปลี่ยน NamePrefix)" }
  } else { Info 'ไม่มีใน soft-delete (ข้าม)' }
}

Step 'เสร็จแล้ว'
Write-Host @"
ตรวจว่าเกลี้ยง:  az resource list -g $rg -o table
deploy ใหม่:     ./scripts/deploy.ps1$(if ($BackupTo) { " -RestoreFrom $BackupTo" })
"@
