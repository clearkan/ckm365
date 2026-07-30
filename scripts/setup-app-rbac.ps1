#Requires -Modules ExchangeOnlineManagement
<#
Scripted Exchange RBAC-for-Applications scoping for the ckm365 GRAPH app
(CKM-5): register its service principal with EXO, create a management
scope covering ONLY the target mailbox, assign the Application
Mail.ReadWrite + Calendars.ReadWrite roles bounded by that scope, and
prove the result with Test-ServicePrincipalAuthorization — including the
out-of-scope NEGATIVE probe, which is the whole security story.

TENANT-TOUCHING. Dry-run by default: prints the plan and exits. -Apply
executes (idempotent — existing objects are kept). Runs unattended when
the CKM365_EXO_* env vars are set (see exo-common.ps1 /
create-exo-automation-app.sh; needs the exchange-admin role), interactive
otherwise.

  ./scripts/setup-app-rbac.ps1 -AppId <graph-app-client-id> `
      -SpObjectId <its-entra-sp-object-id> `
      -Mailbox tst.apponly@tenant-a.example `
      -DenyMailbox operator@tenant-a.example [-Apply]
#>
param(
  [Parameter(Mandatory)][string]$AppId,
  [Parameter(Mandatory)][string]$SpObjectId,
  [Parameter(Mandatory)][string]$Mailbox,
  [string]$DenyMailbox,
  [ValidatePattern('^ckm365-[a-z0-9-]+$')][string]$ScopeName = 'ckm365-app-scope',
  [string]$DisplayName = 'ckm365 app-only',
  [switch]$Apply
)
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot/exo-common.ps1"

$roles = @('Application Mail.ReadWrite', 'Application Calendars.ReadWrite')
$filter = "PrimarySmtpAddress -eq '$Mailbox'"

Write-Host "plan (scope '$ScopeName', app $AppId):"
Write-Host "  1. New-ServicePrincipal -AppId $AppId -ObjectId $SpObjectId"
Write-Host "  2. New-ManagementScope -Name $ScopeName -RecipientRestrictionFilter `"$filter`""
foreach ($r in $roles) {
  Write-Host "  3. New-ManagementRoleAssignment -App $SpObjectId -Role `"$r`" -CustomResourceScope $ScopeName"
}
Write-Host "  4. Test-ServicePrincipalAuthorization: $Mailbox (expect IN scope)" `
  ($DenyMailbox ? "+ $DenyMailbox (expect OUT of scope)" : '(no -DenyMailbox probe given)')
if (-not $Apply) {
  Write-Host 'DRY RUN - nothing changed. Re-run with -Apply to execute.'
  exit 0
}

Connect-Ckm365Exo

if (Get-ServicePrincipal -Identity $SpObjectId -ErrorAction SilentlyContinue) {
  Write-Host "service principal already registered with EXO"
} else {
  New-ServicePrincipal -AppId $AppId -ObjectId $SpObjectId `
    -DisplayName $DisplayName | Out-Null
  Write-Host "registered service principal with EXO"
}

if (Get-ManagementScope -Identity $ScopeName -ErrorAction SilentlyContinue) {
  $existing = (Get-ManagementScope -Identity $ScopeName).RecipientFilter
  Write-Host "scope '$ScopeName' already exists (filter: $existing) - left untouched"
} else {
  New-ManagementScope -Name $ScopeName -RecipientRestrictionFilter $filter | Out-Null
  Write-Host "created management scope '$ScopeName' -> $Mailbox"
}

foreach ($r in $roles) {
  # Deterministic assignment names make this idempotent and give teardown
  # an exact handle.
  $name = "$ScopeName-" + ($r -replace '^Application ', '' -replace '\.', '-').ToLower()
  if (Get-ManagementRoleAssignment -Identity $name -ErrorAction SilentlyContinue) {
    Write-Host "role assignment '$name' already exists"
  } else {
    New-ManagementRoleAssignment -Name $name -App $SpObjectId -Role $r `
      -CustomResourceScope $ScopeName | Out-Null
    Write-Host "assigned '$r' bounded by '$ScopeName' (as '$name')"
  }
}

# Select InScope explicitly — the default table view drops it on narrow
# consoles, and it is the entire point of the probe.
Write-Host "`nauthorization check - in-scope mailbox ($Mailbox):"
Test-ServicePrincipalAuthorization -Identity $SpObjectId -Resource $Mailbox |
  Select-Object RoleName, InScope | Format-Table -AutoSize
if ($DenyMailbox) {
  Write-Host "authorization check - OUT-of-scope mailbox ($DenyMailbox):"
  Test-ServicePrincipalAuthorization -Identity $SpObjectId -Resource $DenyMailbox |
    Select-Object RoleName, InScope | Format-Table -AutoSize
  Write-Host 'the deny row(s) above must show InScope False - if not, STOP: the scope is not restricting.'
} else {
  Write-Host 'WARNING: no -DenyMailbox given - run the negative probe before using the credential.'
}
