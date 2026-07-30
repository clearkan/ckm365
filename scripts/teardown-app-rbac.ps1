#Requires -Modules ExchangeOnlineManagement
<#
Tear down what setup-app-rbac.ps1 created: the scope-bounded role
assignments, the management scope, and (only with -RemoveServicePrincipal)
the EXO service principal registration. Refuses to touch anything whose
name does not start with 'ckm365-'. Dry-run by default; -Apply executes.
Unattended via the CKM365_EXO_* env vars, interactive otherwise.

  ./scripts/teardown-app-rbac.ps1 -ScopeName ckm365-app-scope `
      [-SpObjectId <sp-object-id> -RemoveServicePrincipal] [-Apply]
#>
param(
  [ValidatePattern('^ckm365-[a-z0-9-]+$')][string]$ScopeName = 'ckm365-app-scope',
  [string]$SpObjectId,
  [switch]$RemoveServicePrincipal,
  [switch]$Apply
)
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot/exo-common.ps1"
Connect-Ckm365Exo

$assignments = @(Get-ManagementRoleAssignment -ErrorAction SilentlyContinue |
  Where-Object { $_.Name -like "$ScopeName-*" })
$scope = Get-ManagementScope -Identity $ScopeName -ErrorAction SilentlyContinue

Write-Host "plan:"
foreach ($a in $assignments) { Write-Host "  Remove-ManagementRoleAssignment '$($a.Name)'" }
if ($scope) { Write-Host "  Remove-ManagementScope '$ScopeName'" }
if ($RemoveServicePrincipal -and $SpObjectId) {
  Write-Host "  Remove-ServicePrincipal '$SpObjectId'"
}
if (-not ($assignments -or $scope -or ($RemoveServicePrincipal -and $SpObjectId))) {
  Write-Host "  nothing to do"
  exit 0
}
if (-not $Apply) {
  Write-Host 'DRY RUN - nothing changed. Re-run with -Apply to execute.'
  exit 0
}

foreach ($a in $assignments) {
  Remove-ManagementRoleAssignment -Identity $a.Name -Confirm:$false
  Write-Host "removed role assignment '$($a.Name)'"
}
if ($scope) {
  Remove-ManagementScope -Identity $ScopeName -Confirm:$false
  Write-Host "removed management scope '$ScopeName'"
}
if ($RemoveServicePrincipal -and $SpObjectId) {
  Remove-ServicePrincipal -Identity $SpObjectId -Confirm:$false
  Write-Host "removed EXO service principal '$SpObjectId'"
}
