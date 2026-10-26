// Azure Tag Governance Monitoring - deploy ทุกอย่างลง Resource Group เดียว
//   Storage + Function App (Python) + ACS Email + Workbook (+ สิทธิ์ Reader ระดับ subscription)
targetScope = 'resourceGroup'

@description('Region ของ resource (ใช้ region เดียวกับ RG ได้เลย)')
param location string = resourceGroup().location

@description('tag ที่ใส่ให้ทุก resource ของโปรเจกต์นี้ (มาจาก Tags ใน config)')
param tags object = {}

@description('คำนำหน้าชื่อ resource (ตัวพิมพ์เล็ก/ตัวเลข ไม่เกิน 8 ตัว)')
@maxLength(8)
param namePrefix string = 'tagGov'

@description('ผู้รับเมลสรุปรายสัปดาห์ (To) คั่นหลายคนด้วยคอมมา')
param mailTo string

@description('Cc ทุกฉบับ คั่นด้วยคอมมา (ว่างได้) ส่วน Cc เฉพาะเมลขั้น 2 ใช้ mailCcEscalation')
param mailCc string = ''
param mailCcEscalation string = ''
param rgNameRegex string = ''

@description('เปิด endpoint /api/run สำหรับทดสอบมือไหม (ค่าเริ่มต้น false = ปิด เพราะ dry_run=0 ส่งเมลและบันทึก state ได้)')
param enableTestEndpoint bool = false

@description('เปิด endpoint POST /api/send สำหรับส่งเมลรายงานทันทีตอนไหนก็ได้ไหม (ไม่บันทึก state จึงไม่กระทบรอบ escalation)')
param enableManualSend bool = false

@description('ชื่อ Policy assignment ที่ใช้ตรวจ')
param assignmentName string = 'rg-tag-governance-audit'

@description('Subscription ID ที่ต้องการตรวจ คั่นด้วยคอมมา (เว้นว่าง = ทุก subscription ที่ identity อ่านได้)')
param subscriptionIds string = ''

@description('ค้างครบกี่วันถึงยกระดับ')
param slaDays int = 14

@description('สร้าง Azure Communication Services Email ใหม่ไหม (false = ใช้ของที่มีอยู่ ต้องใส่ acsConnectionString และ mailSender)')
param createAcs bool = true

@secure()
@description('ใช้เมื่อ createAcs = false')
param acsConnectionString string = ''

@description('ที่อยู่ผู้ส่ง ใช้เมื่อ createAcs = false')
param mailSender string = ''

@description('ให้สิทธิ์ Reader แก่ Function ที่ระดับ subscription (ผู้ deploy ต้องเป็น Owner / User Access Administrator) ถ้าไม่มีสิทธิ์ ตั้งเป็น false แล้วให้ admin ทำทีหลัง')
param assignSubscriptionReader bool = true

@description('false = เก็บ snapshot อย่างเดียว ยังไม่ส่งเมล (ใช้ช่วงสัปดาห์แรกก่อนเริ่มส่งจริง) เปลี่ยนเป็น true ภายหลังที่ App setting TG_MAIL_ENABLED')
param mailEnabled bool = true

@description('ลิงก์ Workbook ที่จะใส่ในเมล (เว้นว่าง = ระบบสร้างให้จากชื่อ Workbook)')
param workbookUrlOverride string = ''

@description('เก็บ snapshot รายวันใน Blob กี่วันก่อนลบอัตโนมัติ (snapshot มีค่า tag owner ซึ่งเป็นอีเมลของคน จึงไม่ควรเก็บตลอดไป ไม่กระทบ state.json)')
@minValue(30)
param snapshotRetentionDays int = 365

@secure()
@description('ค่า WEBSITE_RUN_FROM_PACKAGE เดิมของ Function (สคริปต์อ่านมาให้) เพื่อไม่ให้การ deploy โครงสร้างซ้ำลบโค้ดที่ส่งไปแล้ว')
param runFromPackage string = ''

var uniq = uniqueString(resourceGroup().id)
var storageName = toLower('st${take(namePrefix, 8)}${take(uniq, 12)}')
var funcName = '${namePrefix}-func-${take(uniq, 6)}'
var planName = '${namePrefix}-plan'
var lawName = '${namePrefix}-law'
var aiName = '${namePrefix}-ai'
var kvName = '${take(namePrefix, 8)}kv${take(uniq, 10)}'
var workbookGuid = guid(resourceGroup().id, 'tag-governance-workbook')

// ---------------- Storage (ทั้งสำหรับ Function และเก็บ snapshot/state) ----------------
resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: storageName
  location: location
  tags: tags
  sku: { name: 'Standard_LRS' }
  kind: 'StorageV2'
  properties: {
    minimumTlsVersion: 'TLS1_2'
    allowBlobPublicAccess: false
    allowCrossTenantReplication: false
    supportsHttpsTrafficOnly: true
  }
}
// soft delete: ถ้า state.json ถูกลบหรือเขียนทับผิด กู้คืนได้ภายใน 14 วัน (ถ้า state หาย อายุของทุกรายการจะเริ่มนับใหม่)
resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storage
  name: 'default'
  properties: {
    deleteRetentionPolicy: { enabled: true, days: 14 }
    containerDeleteRetentionPolicy: { enabled: true, days: 14 }
  }
}
// ลบ snapshot ที่เก่ากว่า snapshotRetentionDays (เฉพาะโฟลเดอร์ snapshots/ ใน container tag-governance)
resource lifecycle 'Microsoft.Storage/storageAccounts/managementPolicies@2023-05-01' = {
  parent: storage
  name: 'default'
  properties: {
    policy: {
      rules: [
        {
          enabled: true
          name: 'expire-snapshots'
          type: 'Lifecycle'
          definition: {
            filters: { blobTypes: [ 'blockBlob' ], prefixMatch: [ 'tag-governance/snapshots/' ] }
            actions: { baseBlob: { delete: { daysAfterModificationGreaterThan: snapshotRetentionDays } } }
          }
        }
      ]
    }
  }
}
var storageConn = 'DefaultEndpointsProtocol=https;AccountName=${storage.name};AccountKey=${storage.listKeys().keys[0].value};EndpointSuffix=${environment().suffixes.storage}'

// ---------------- Logs ----------------
resource law 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: lawName
  location: location
  tags: tags
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
    // เพดาน log ต่อวัน กันค่าใช้จ่ายบานเมื่อมีอะไรผิดปกติ (ใช้งานปกติไม่กี่ MB ต่อวัน) เกินแล้วหยุดเก็บ log จนถึงวันถัดไป
    workspaceCapping: { dailyQuotaGb: json('0.1') }
  }
}
resource ai 'Microsoft.Insights/components@2020-02-02' = {
  name: aiName
  location: location
  tags: tags
  kind: 'web'
  properties: { Application_Type: 'web', WorkspaceResourceId: law.id }
}

// ---------------- ACS Email (ตัวเลือก) ----------------
resource emailService 'Microsoft.Communication/emailServices@2023-04-01' = if (createAcs) {
  name: '${namePrefix}-email-${take(uniq, 6)}'
  location: 'global'
  tags: tags
  properties: { dataLocation: 'Asia Pacific' }
}
resource emailDomain 'Microsoft.Communication/emailServices/domains@2023-04-01' = if (createAcs) {
  parent: emailService
  name: 'AzureManagedDomain'
  location: 'global'
  tags: tags
  properties: { domainManagement: 'AzureManaged' }
}
resource acs 'Microsoft.Communication/communicationServices@2023-04-01' = if (createAcs) {
  name: '${namePrefix}-acs-${take(uniq, 6)}'
  location: 'global'
  tags: tags
  properties: {
    dataLocation: 'Asia Pacific'
    linkedDomains: [ emailDomain.id ]
  }
}
var acsConn = createAcs ? acs!.listKeys().primaryConnectionString : acsConnectionString
var sender = createAcs ? 'DoNotReply@${emailDomain!.properties.mailFromSenderDomain}' : mailSender

// ---------------- Key Vault (เก็บ ACS connection string แทนการใส่ตรงใน App settings) ----------------
resource kv 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: kvName
  location: location
  tags: tags
  properties: {
    sku: { family: 'A', name: 'standard' }
    tenantId: subscription().tenantId
    enableRbacAuthorization: true
    enableSoftDelete: true
  }
}
resource acsSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: kv
  name: 'acs-connection-string'
  properties: { value: acsConn }
}

// ---------------- Workbook ----------------
resource workbook 'Microsoft.Insights/workbooks@2023-06-01' = {
  name: workbookGuid
  location: location
  tags: tags
  kind: 'shared'
  properties: {
    displayName: 'Tag Governance - รายการที่ยังไม่ผ่าน'
    category: 'workbook'
    sourceId: 'Azure Monitor'
    version: '1.0'
    serializedData: loadTextContent('../workbook/tag-governance.workbook.json')
  }
}
var workbookUrl = empty(workbookUrlOverride) ? 'https://portal.azure.com/#blade/AppInsightsExtension/UsageNotebookBlade/ComponentId/Azure%20Monitor/ConfigurationId/${uriComponent(workbook.id)}/Type/workbook/WorkbookTemplateName/' : workbookUrlOverride

// ---------------- Function App ----------------
resource plan 'Microsoft.Web/serverfarms@2023-12-01' = {
  name: planName
  location: location
  tags: tags
  kind: 'linux'
  sku: { name: 'Y1', tier: 'Dynamic' }
  properties: { reserved: true }
}

resource func 'Microsoft.Web/sites@2023-12-01' = {
  name: funcName
  location: location
  tags: tags
  kind: 'functionapp,linux'
  identity: { type: 'SystemAssigned' }
  properties: {
    serverFarmId: plan.id
    httpsOnly: true
    siteConfig: {
      linuxFxVersion: 'Python|3.11'
      minTlsVersion: '1.2'
      ftpsState: 'Disabled'
      // appSettings แทนที่ค่าทั้งชุด จึงต้องใส่ WEBSITE_RUN_FROM_PACKAGE เดิมกลับไป (Linux Consumption ใช้ค่านี้ชี้ไปที่โค้ด)
      appSettings: concat([
        { name: 'AzureWebJobsStorage', value: storageConn }
        { name: 'WEBSITE_CONTENTAZUREFILECONNECTIONSTRING', value: storageConn }
        { name: 'WEBSITE_CONTENTSHARE', value: toLower(funcName) }
        { name: 'FUNCTIONS_EXTENSION_VERSION', value: '~4' }
        { name: 'FUNCTIONS_WORKER_RUNTIME', value: 'python' }
        { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: ai.properties.ConnectionString }
        { name: 'SCM_DO_BUILD_DURING_DEPLOYMENT', value: 'true' }
        { name: 'ENABLE_ORYX_BUILD', value: 'true' }
        { name: 'TG_ASSIGNMENT_NAME', value: assignmentName }
        { name: 'TG_SUBSCRIPTION_IDS', value: subscriptionIds }
        { name: 'TG_SLA_DAYS', value: string(slaDays) }
        { name: 'TG_MAIL_ENABLED', value: string(mailEnabled) }
        { name: 'TG_MAIL_TO', value: mailTo }
        { name: 'TG_MAIL_CC', value: mailCc }
        { name: 'TG_MAIL_CC_ESCALATION', value: mailCcEscalation }
        { name: 'TG_RG_NAME_REGEX', value: rgNameRegex }
        { name: 'TG_HTTP_ENABLED', value: string(enableTestEndpoint) }
        { name: 'TG_MANUAL_SEND_ENABLED', value: string(enableManualSend) }
        { name: 'TG_MAIL_SENDER', value: sender }
        { name: 'TG_ACS_CONNECTION_STRING', value: '@Microsoft.KeyVault(SecretUri=${acsSecret.properties.secretUri})' }
        { name: 'TG_WORKBOOK_URL', value: workbookUrl }
      ], empty(runFromPackage) ? [] : [
        { name: 'WEBSITE_RUN_FROM_PACKAGE', value: runFromPackage }
      ])
    }
  }
}

// Key Vault Secrets User: ให้ Function อ่าน secret ได้อย่างเดียว
resource kvRead 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: kv
  name: guid(kv.id, func.id, 'secrets-user')
  properties: {
    principalId: func.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '4633458b-17de-408a-b874-0445c86b69e6')
  }
}

module reader 'role-reader.bicep' = if (assignSubscriptionReader) {
  name: 'tagGovReader'
  scope: subscription()
  params: { principalId: func.identity.principalId }
}

output functionAppName string = func.name
output functionPrincipalId string = func.identity.principalId
output mailSender string = sender
output workbookName string = workbook.properties.displayName
output workbookResourceId string = workbook.id
