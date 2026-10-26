<#
.SYNOPSIS
  Deploy Azure Tag Governance Monitor ทั้งชุด (Storage + Function + ACS Email + Workbook) ลง Resource Group เดียว
  ค่าทั้งหมดอ่านจาก config/deploy.config.psd1 (ไฟล์นี้ไม่ถูก push ขึ้น repo)

.DESCRIPTION
  ลำดับการทำงาน:
    1. อ่านและตรวจ config   2. ตรวจว่า az login อยู่ subscription ที่ถูกต้อง
    3. ตรวจ Resource Group: ถ้ามีอยู่แล้ว -> แจ้งและให้พิมพ์ชื่อ RG ยืนยัน, ถ้ายังไม่มี -> แจ้งว่าจะสร้างใหม่และให้ยืนยัน
    4. (-PlanOnly) แสดง what-if แล้วหยุด   5. deploy Bicep   6. ส่งโค้ด Function
  สคริปต์ไม่ลบอะไรเลย (deploy แบบ incremental) และไม่แตะ resource อื่นใน RG

.PARAMETER ConfigPath  ไฟล์ config (ค่าเริ่มต้น config/deploy.config.psd1)
.PARAMETER PlanOnly    ดูว่าจะทำอะไรโดยไม่เปลี่ยนแปลงอะไรเลย (what-if)
.PARAMETER Yes         ข้ามคำถามยืนยัน (สำหรับรันอัตโนมัติ) ยังพิมพ์สรุปให้เห็นเสมอ
.PARAMETER Part        All (ค่าเริ่มต้น) | Infra = เฉพาะโครงสร้าง | Code = ส่งเฉพาะโค้ด Function (ใช้หลังแก้โค้ด)
.PARAMETER RestoreFrom โฟลเดอร์ที่ได้จาก teardown.ps1 -BackupTo: คืน state.json และ snapshots ขึ้น Storage ใหม่หลัง deploy (age ของรายการจึงนับต่อ ไม่เริ่มใหม่)
.PARAMETER Set         กำหนดหรือทับค่าใน config จากบรรทัดคำสั่ง เช่น -Set @{ MailEnabled = $true } (ไม่ถูกบันทึกลงไฟล์)

.EXAMPLE
  ./scripts/deploy.ps1 -PlanOnly          # ดูก่อน ไม่แก้อะไร
  ./scripts/deploy.ps1                    # deploy จริง (มีถามยืนยัน)
  ./scripts/deploy.ps1 -Part Code         # แก้โค้ดแล้วส่งซ้ำ
  ./scripts/deploy.ps1
  ./scripts/deploy.ps1 -Set @{ ResourceGroup = 'rg-lab'; MailEnabled = $false }   # ทับบางค่า

ต้องมี: PowerShell 5.1 หรือ 7+, Azure CLI (az) ที่ login แล้ว, สิทธิ์ Contributor บน RG
        (และต้องมีสิทธิ์สร้าง role assignment หาก AssignSubscriptionReader = $true)
#>
[CmdletBinding()]
param(
  [string]$ConfigPath = (Join-Path (Split-Path -Parent $PSScriptRoot) 'config/deploy.config.psd1'),
  [switch]$PlanOnly,
  [switch]$Yes,
  [ValidateSet('All', 'Infra', 'Code')] [string]$Part = 'All',
  [string]$RestoreFrom,
  [hashtable]$Set = @{}
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot

function Step($m) { Write-Host "`n==> $m" -ForegroundColor Cyan }
function Fail($m) { Write-Host "`nERROR: $m" -ForegroundColor Red; exit 1 }
function Info($m) { Write-Host "    $m" }
function Warn($m) { Write-Host "    ! $m" -ForegroundColor Yellow }

# ---------- 1) อ่านและตรวจ config ----------
Step "อ่าน config: $ConfigPath"
if (Test-Path $ConfigPath) {
  $cfg = Import-PowerShellDataFile -Path $ConfigPath   # อ่านเป็นข้อมูลล้วน ไม่รันโค้ดในไฟล์
} elseif ($Set.Count -gt 0) {
  Info 'ไม่พบไฟล์ config จะใช้เฉพาะค่าจาก -Set'
  $cfg = @{}
} else {
  Fail "ไม่พบไฟล์ config`n    สร้างจากตัวอย่าง:  Copy-Item config/deploy.config.example.psd1 config/deploy.config.psd1`n    แล้วแก้ค่าในไฟล์ใหม่ (ไฟล์จริงถูก .gitignore กันไว้ ไม่ถูก push)"
}
foreach ($k in $Set.Keys) { $cfg[$k] = $Set[$k] }   # ค่าจากบรรทัดคำสั่งมาก่อนค่าในไฟล์

if ($RestoreFrom -and -not (Test-Path (Join-Path $RestoreFrom 'state.json'))) {
  Write-Host "    ! -RestoreFrom: ไม่พบ state.json ใน '$RestoreFrom' (ระบบเดิมอาจยังไม่เคยรัน) จะข้ามการคืน state" -ForegroundColor Yellow
  $RestoreFrom = ''
}

$known = @('SubscriptionId', 'ResourceGroup', 'Location', 'Tags', 'ResourceGroupTags', 'NamePrefix', 'PolicyAssignmentName',
  'ScanSubscriptionIds', 'RgNameRegex', 'SlaDays', 'MailEnabled', 'MailTo', 'MailCc', 'MailCcEscalation',
  'MailMaxItems', 'CreateAcsEmail', 'ExistingAcsSender', 'AssignSubscriptionReader', 'EnableTestEndpoint', 'EnableManualSend'
  )
foreach ($k in $cfg.Keys) { if ($known -notcontains $k) { Fail "config มี key ที่ไม่รู้จัก '$k' (พิมพ์ผิดหรือเปล่า) key ที่ใช้ได้: $($known -join ', ')" } }

function Cfg($key, $default) { if ($cfg.ContainsKey($key) -and $null -ne $cfg[$key]) { $cfg[$key] } else { $default } }
function AsList($v) { @($v) | Where-Object { $_ -and "$_".Trim() } | ForEach-Object { "$_".Trim() } }
$guidRx = '^[0-9a-fA-F]{8}-([0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$'
$mailRx = '^[^@\s]+@[^@\s]+\.[^@\s]+$'
$errors = New-Object System.Collections.Generic.List[string]

$subId = "$(Cfg 'SubscriptionId' '')"
if ($subId -notmatch $guidRx -or $subId -eq '00000000-0000-0000-0000-000000000000') { $errors.Add("SubscriptionId ต้องเป็น GUID จริงของ subscription (ตอนนี้: '$subId')") }
$rg = "$(Cfg 'ResourceGroup' '')"
if ($rg -notmatch '^[\w.()-]{1,90}$' -or $rg.EndsWith('.')) { $errors.Add("ResourceGroup ไม่ถูกต้อง (ใช้ตัวอักษร/ตัวเลข . _ - ( ) ไม่เกิน 90 ตัว และห้ามลงท้ายด้วยจุด): '$rg'") }
$location = "$(Cfg 'Location' '')"
if (-not $location) { $errors.Add('ต้องระบุ Location เช่น southeastasia') }
$prefix = "$(Cfg 'NamePrefix' 'tagGov')"
if ($prefix -notmatch '^[A-Za-z0-9]{1,8}$') { $errors.Add("NamePrefix ต้องเป็นตัวอักษร/ตัวเลข 1-8 ตัว: '$prefix'") }
$mailTo = AsList (Cfg 'MailTo' @())
$mailCc = AsList (Cfg 'MailCc' @())
$mailCcEsc = AsList (Cfg 'MailCcEscalation' @())
if ($mailTo.Count -eq 0) { $errors.Add('MailTo ต้องมีอย่างน้อย 1 อีเมล') }
foreach ($m in (@($mailTo) + @($mailCc) + @($mailCcEsc))) {
  if ($m -notmatch $mailRx) { $errors.Add("อีเมลไม่ถูกต้อง: '$m'") }
  elseif ($m -match '@example\.(com|org|net)$') { $errors.Add("อีเมล '$m' ยังเป็นค่าตัวอย่าง ให้ใส่อีเมลจริง") }
}
$scanIds = AsList (Cfg 'ScanSubscriptionIds' @())
foreach ($s in $scanIds) { if ($s -notmatch $guidRx) { $errors.Add("ScanSubscriptionIds มีค่าที่ไม่ใช่ GUID: '$s'") } }
$sla = [int](Cfg 'SlaDays' 14)
if ($sla -lt 1) { $errors.Add('SlaDays ต้องมากกว่า 0') }
$mailMaxItems = [int](Cfg 'MailMaxItems' 10)
if ($mailMaxItems -lt 1) { $errors.Add('MailMaxItems ต้องมากกว่า 0') }
$rgRegex = "$(Cfg 'RgNameRegex' '')"
if ($rgRegex) { try { [void][regex]::new($rgRegex) } catch { $errors.Add("RgNameRegex ไม่ใช่ regex ที่ถูกต้อง: $rgRegex") } }
$createAcs = [bool](Cfg 'CreateAcsEmail' $true)
$acsConn = ''
$acsSender = ''
if (-not $createAcs) {
  $acsSender = "$(Cfg 'ExistingAcsSender' '')"
  $acsConn = "$env:TG_ACS_CONNECTION_STRING"
  if ($acsSender -notmatch $mailRx) { $errors.Add('CreateAcsEmail = $false ต้องระบุ ExistingAcsSender (ที่อยู่ผู้ส่งของ ACS ที่มีอยู่)') }
  if (-not $acsConn) { $errors.Add('CreateAcsEmail = $false ต้องตั้ง environment variable TG_ACS_CONNECTION_STRING ในเครื่องที่รันสคริปต์ (ห้ามใส่ใน config)') }
}
if ($errors.Count -gt 0) { Fail ("config ไม่ถูกต้อง:`n  - " + ($errors -join "`n  - ")) }

$mailEnabled = [bool](Cfg 'MailEnabled' $true)
$assignReader = [bool](Cfg 'AssignSubscriptionReader' $true)
$testEndpoint = [bool](Cfg 'EnableTestEndpoint' $false)
$manualSend = [bool](Cfg 'EnableManualSend' $false)
# Tags ใส่ให้ RG ที่สร้างใหม่และทุก resource ของโปรเจกต์ (ResourceGroupTags คือชื่อเดิม ยังใช้ได้)
$tagCfg = Cfg 'Tags' (Cfg 'ResourceGroupTags' @{})
$tagMap = [ordered]@{}
foreach ($k in $tagCfg.Keys) { $tagMap["$k"] = "$($tagCfg[$k])" }
$tags = @()
foreach ($k in $tagMap.Keys) { $tags += "$k=$($tagMap[$k])" }

# ---------- 2) ตรวจ Azure CLI และ subscription ----------
Step 'ตรวจ Azure CLI'
if (-not (Get-Command az -ErrorAction SilentlyContinue)) { Fail 'ไม่พบ Azure CLI (az) ติดตั้งที่ https://learn.microsoft.com/cli/azure/install-azure-cli' }
$acctJson = & az account show -o json 2>$null
if ($LASTEXITCODE -ne 0 -or -not $acctJson) { Fail 'ยังไม่ได้ login  รัน:  az login  (หรือ az login --tenant <tenant-id>)' }
$acct = $acctJson | ConvertFrom-Json
Info "ผู้ใช้:        $($acct.user.name)"
Info "Subscription: $($acct.name) ($($acct.id))"
if ($acct.id -ne $subId) {
  Fail "az login อยู่คนละ subscription กับใน config`n    ตอนนี้: $($acct.id)`n    config:  $subId`n    สลับด้วย:  az account set --subscription $subId   แล้วรันใหม่"
}


# ---------- 3) ตรวจ Resource Group ----------
Step "ตรวจ Resource Group '$rg'"
$rgExists = ((& az group exists --name $rg -o tsv) -eq 'true')
$existing = @()
if ($rgExists) {
  $existing = @(& az resource list --resource-group $rg --query "[].{n:name,t:type}" -o json | ConvertFrom-Json)
  Warn "RG '$rg' มีอยู่แล้วใน subscription นี้ มี $($existing.Count) resource"
  $existing | Select-Object -First 15 | ForEach-Object { Info "  - $($_.n)   [$($_.t)]" }
  if ($existing.Count -gt 15) { Info "  ... และอีก $($existing.Count - 15) รายการ" }
  # ห้ามมีระบบนี้ 2 ชุด (NamePrefix ต่างกัน) ใน RG เดียว: Workbook ชนกัน และ teardown ของชุดหนึ่งเคยลบอีกชุดไปด้วย
  $depList = (& az deployment group list --resource-group $rg -o json) | ConvertFrom-Json
  $others = @($depList | Where-Object { $_.name -like 'tag-governance-*' } |
    ForEach-Object { if ($_.properties.parameters.namePrefix.value) { "$($_.properties.parameters.namePrefix.value)" } else { 'tagGov' } } |
    Where-Object { $_ -ne $prefix } | Sort-Object -Unique)
  if ($others.Count) {
    Fail ("RG '$rg' มีระบบนี้อีกชุดอยู่แล้ว (NamePrefix: $($others -join ', ')) แต่ config นี้ใช้ NamePrefix '$prefix'`n" +
      "    ห้าม deploy 2 ชุดลง RG เดียวกัน เลือกอย่างใดอย่างหนึ่ง:`n" +
      "    - จะอัปเดตชุดเดิม: ตั้ง NamePrefix ใน config ให้ตรงกับชุดเดิม`n" +
      "    - จะทดสอบแยก: ใช้ RG อื่น`n" +
      "    - จะแทนที่ชุดเดิม: ลบชุดเดิมก่อนด้วย teardown.ps1 โดยใช้ NamePrefix ของชุดเดิม (docs/OPERATIONS.md หัวข้อ 8)")
  }
  Warn 'จะ deploy resource ของโปรเจกต์นี้เพิ่ม/อัปเดตลงใน RG นี้ (ไม่ลบ ไม่แก้ resource อื่น และไม่แก้ tag/region ของ RG)'
  if ($tags.Count) { Info "tag ที่จะใส่ให้ resource ของโปรเจกต์: $($tags -join ', ')  (RG ที่มีอยู่แล้วไม่ถูกแก้ tag)" }
} else {
  Info "RG '$rg' ยังไม่มี -> จะสร้างใหม่ที่ $location"
  if ($tags.Count) { Info "tag ที่จะใส่ให้ RG และ resource ของโปรเจกต์: $($tags -join ', ')" } else { Warn 'ไม่ได้ตั้ง Tags (ถ้า Policy ของคุณบังคับ tag บน RG ตัว RG นี้จะไม่ผ่านเอง ดู config)' }
}

Step 'สรุปสิ่งที่จะทำ'
if ($Set.Count) { Info "ค่าจาก -Set:      $(($Set.Keys | Sort-Object) -join ', ') (ทับค่าใน config)" }
Info "ส่วนที่ deploy:   $Part"
Info "ส่งเมลจริง:       $(if ($mailEnabled) { 'ใช่' } else { 'ไม่ (เก็บ snapshot อย่างเดียว)' })"
Info "To:               $($mailTo -join ', ')"
Info "Cc ทุกฉบับ:       $(if ($mailCc.Count) { $mailCc -join ', ' } else { '-' })"
Info "Cc เมลขั้น 2:     $(if ($mailCcEsc.Count) { $mailCcEsc -join ', ' } else { '-' })"
Info "ACS Email:        $(if ($createAcs) { 'สร้างใหม่ (managed domain)' } else { "ใช้ของเดิม ($acsSender)" })"
Info "Policy assignment ที่ตรวจ: $(Cfg 'PolicyAssignmentName' 'rg-tag-governance-audit')"
Info "Endpoint ทดสอบ /api/run:   $(if ($testEndpoint) { 'เปิด (อย่าลืมปิดหลังทดสอบ)' } else { 'ปิด' })"
Info "ส่งเมลทันที /api/send:     $(if ($manualSend) { 'เปิด' } else { 'ปิด' })"
if ($assignReader) { Info "จะมอบสิทธิ์ Reader ให้ Function (managed identity) ที่ระดับ subscription $subId" }

# ---------- เตรียมไฟล์พารามิเตอร์ (ไม่ใส่ค่าลงบรรทัดคำสั่ง) ----------
$paramFile = $null
function Get-RunFromPackage {
  if (-not $rgExists) { return $null }
  $fn = & az functionapp list --resource-group $rg --query "[?starts_with(name,'$prefix-func-')].name | [0]" -o tsv
  if (-not $fn) { return $null }
  $v = & az functionapp config appsettings list --resource-group $rg --name $fn --query "[?name=='WEBSITE_RUN_FROM_PACKAGE'].value | [0]" -o tsv
  if ($LASTEXITCODE -ne 0) { return $null }
  return $v
}

function Write-ParamFile {
  $p = [ordered]@{
    mailTo = ($mailTo -join ','); mailCc = ($mailCc -join ','); mailCcEscalation = ($mailCcEsc -join ',')
    namePrefix = $prefix; assignmentName = "$(Cfg 'PolicyAssignmentName' 'rg-tag-governance-audit')"
    subscriptionIds = ($scanIds -join ','); rgNameRegex = $rgRegex; slaDays = $sla; mailMaxItems = $mailMaxItems
    mailEnabled = $mailEnabled; createAcs = $createAcs; assignSubscriptionReader = $assignReader
    enableTestEndpoint = $testEndpoint; enableManualSend = $manualSend
    tags = $tagMap
  }
  if (-not $createAcs) { $p.acsConnectionString = $acsConn; $p.mailSender = $acsSender }
  # Bicep เขียน appSettings ทับทั้งชุด ถ้าไม่ส่งค่าเดิมกลับไป โค้ดที่ deploy แล้วจะหาย (Function App ว่าง)
  $pkg = Get-RunFromPackage
  if ($pkg) { $p.runFromPackage = $pkg }
  $wrap = [ordered]@{}
  foreach ($k in $p.Keys) { $wrap[$k] = @{ value = $p[$k] } }
  $doc = [ordered]@{
    '$schema' = 'https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#'
    contentVersion = '1.0.0.0'; parameters = $wrap
  }
  $f = [IO.Path]::GetTempFileName()
  $doc | ConvertTo-Json -Depth 6 | Set-Content -Path $f -Encoding UTF8
  return $f
}

try {
  # ---------- 4) PlanOnly ----------
  if ($PlanOnly) {
    Step 'โหมด -PlanOnly: ไม่เปลี่ยนแปลงอะไรเลย'
    if ($Part -eq 'Code') { Info 'ส่วน Code ไม่มี what-if: จะ zip โฟลเดอร์ function/ แล้วส่งขึ้น Function App ที่มีอยู่'; exit 0 }
    if (-not $rgExists) { Info "RG ยังไม่มี จึงยังรัน what-if ไม่ได้ ผลที่คาด: สร้าง RG + resource ทั้งหมดของโปรเจกต์"; exit 0 }
    $paramFile = Write-ParamFile
    & az deployment group what-if --resource-group $rg --template-file "$root/infra/main.bicep" --parameters "@$paramFile"
    if ($LASTEXITCODE -ne 0) { Fail 'what-if ไม่สำเร็จ ดูข้อความด้านบน' }
    exit 0
  }

  # ---------- ยืนยัน ----------
  if (-not $Yes) {
    Write-Host ''
    if ($rgExists) { $ans = Read-Host "RG มีอยู่แล้ว: พิมพ์ชื่อ RG '$rg' เพื่อยืนยันว่าจะ deploy ลงที่นี่ (หรือ Enter เพื่อยกเลิก)"; $ok = ($ans -eq $rg) }
    else { $ans = Read-Host "ยืนยันสร้าง RG ใหม่ '$rg' และ deploy พิมพ์ yes (หรือ Enter เพื่อยกเลิก)"; $ok = ($ans -eq 'yes') }
    if (-not $ok) { Write-Host 'ยกเลิก ไม่มีอะไรถูกเปลี่ยน'; exit 0 }
  }

  $funcName = $null
  # ---------- 5) Infra ----------
  if ($Part -in 'All', 'Infra') {
    if (-not $rgExists) {
      Step "สร้าง Resource Group $rg ($location)"
      $a = @('group', 'create', '--name', $rg, '--location', $location, '-o', 'none')
      if ($tags.Count) { $a += '--tags'; $a += $tags }
      & az @a
      if ($LASTEXITCODE -ne 0) { Fail 'สร้าง RG ไม่สำเร็จ (สิทธิ์พอไหม? ชื่อซ้ำกับ RG ใน region อื่นไหม?)' }
    }
    Step 'Deploy โครงสร้าง (Bicep)'
    $paramFile = Write-ParamFile
    $outJson = & az deployment group create --resource-group $rg --name "tag-governance-$(Get-Date -Format yyyyMMddHHmmss)" `
      --template-file "$root/infra/main.bicep" --parameters "@$paramFile" --query properties.outputs -o json
    if ($LASTEXITCODE -ne 0) {
      Fail "deploy Bicep ไม่สำเร็จ ดูข้อความด้านบน"
    }
    $out = $outJson | ConvertFrom-Json
    $funcName = $out.functionAppName.value
    Info "Function App: $funcName"
    Info "ผู้ส่งเมล:     $($out.mailSender.value)"
    $principal = $out.functionPrincipalId.value
  }

  # ---------- 6) Code ----------
  if ($Part -in 'All', 'Code') {
    if (-not $funcName) {
      $funcName = & az functionapp list --resource-group $rg --query "[?starts_with(name,'$prefix-func-')].name | [0]" -o tsv
      if (-not $funcName) { Fail "ไม่พบ Function App ('$prefix-func-*') ใน RG $rg ให้รันด้วย -Part All หรือ Infra ก่อน" }
    }
    Step 'แพ็กโค้ด Function'
    $stage = Join-Path ([IO.Path]::GetTempPath()) "tg-func-$(Get-Random)"
    New-Item -ItemType Directory $stage | Out-Null
    Copy-Item "$root/function/*" $stage -Recurse -Exclude '__pycache__', 'local.settings.json', 'local.settings.sample.json'
    Get-ChildItem $stage -Recurse -Directory -Filter '__pycache__' -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force
    $zip = Join-Path ([IO.Path]::GetTempPath()) "tg-func-$(Get-Random).zip"
    # สร้าง entry เองด้วย '/' : ZipFile.CreateFromDirectory บน Windows PowerShell 5.1 ใช้ '\' คั่น path
    # ทำให้บน Linux ไม่มีโฟลเดอร์ tag_governance/ -> import พัง -> Function App ไม่เห็น function เลย
    Add-Type -AssemblyName System.IO.Compression, System.IO.Compression.FileSystem
    $stageFull = (Resolve-Path $stage).Path.TrimEnd('\', '/')
    $archive = [IO.Compression.ZipFile]::Open($zip, [IO.Compression.ZipArchiveMode]::Create)
    try {
      foreach ($f in Get-ChildItem $stageFull -Recurse -File) {
        $entry = $f.FullName.Substring($stageFull.Length + 1).Replace('\', '/')
        [void][IO.Compression.ZipFileExtensions]::CreateEntryFromFile($archive, $f.FullName, $entry)
      }
    }
    finally { $archive.Dispose() }
    Step "ส่งโค้ดขึ้น Function App $funcName (build บน Azure)"
    & az functionapp deployment source config-zip --resource-group $rg --name $funcName --src $zip --build-remote true -o none
    $code = $LASTEXITCODE
    Remove-Item $stage -Recurse -Force; Remove-Item $zip -Force
    if ($code -ne 0) { Fail 'ส่งโค้ดไม่สำเร็จ ดูข้อความด้านบน' }
    Step 'ตรวจว่า Function App เห็น function'
    $names = @()
    for ($i = 0; $i -lt 6 -and -not $names; $i++) {
      Start-Sleep -Seconds 10
      $names = @(& az functionapp function list --resource-group $rg --name $funcName --query '[].name' -o tsv | Where-Object { $_ })
    }
    if ($names) { Info "พบ function: $($names -join ', ')" }
    else {
      Write-Warning ("ส่งโค้ดสำเร็จแต่ยังไม่เห็น function ใน $funcName (มักเกิดจาก import error ตอนโหลด function_app.py)`n" +
        "    ดู log: Portal > $funcName > Log stream หรือ Application Insights > traces / exceptions")
    }
  }

  # ---------- คืน state จาก backup ----------
  if ($RestoreFrom) {
    Step "คืน state จาก $RestoreFrom"
    $stName = & az storage account list --resource-group $rg --query "[?starts_with(name,'st$($prefix.ToLower())')].name | [0]" -o tsv
    if (-not $stName) { Fail 'ไม่พบ Storage account ใน RG (ต้อง deploy Infra ก่อน)' }
    $env:AZURE_STORAGE_KEY = (& az storage account keys list --account-name $stName --resource-group $rg --query "[0].value" -o tsv)
    try {
      & az storage container create --account-name $stName --name tag-governance -o none
      & az storage blob upload-batch --account-name $stName --destination tag-governance --source $RestoreFrom --overwrite true -o none
      if ($LASTEXITCODE -ne 0) { Fail 'คืน state ไม่สำเร็จ' }
    } finally { Remove-Item Env:\AZURE_STORAGE_KEY -ErrorAction SilentlyContinue }
    Info 'คืน state.json และ snapshots แล้ว'
  }

  # ---------- 7) ขั้นถัดไป ----------
  Step 'เสร็จแล้ว - ขั้นตอนถัดไป'
  if (-not $testEndpoint) {
    Write-Host '1) Endpoint ทดสอบ /api/run ปิดอยู่ (EnableTestEndpoint = $false)'
    Write-Host '   เปิดชั่วคราว: ./scripts/deploy.ps1 -Part Infra -Set @{ EnableTestEndpoint = $true }'
    Write-Host '   ทดสอบเสร็จแล้วปิดกลับ: ./scripts/deploy.ps1 -Part Infra'
  } else {
    Write-Host '1) ทดสอบ dry-run (ไม่ส่งเมลและไม่บันทึก state):'
    Write-Host "   `$key = az functionapp function keys list -g $rg -n $funcName --function-name run_now --query default -o tsv"
    Write-Host "   Invoke-RestMethod -Headers @{ `"x-functions-key`" = `$key } `"https://$funcName.azurewebsites.net/api/run?dry_run=1&force=1`" | ConvertTo-Json -Depth 6"
  }
}
finally {
  if ($paramFile -and (Test-Path $paramFile)) { Remove-Item $paramFile -Force }   # ไฟล์นี้อาจมี connection string
}
