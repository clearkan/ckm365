#Requires -Modules ExchangeOnlineManagement
<#
Remove a tst.<suffix> shared test mailbox created by create-test-mailbox.ps1.
Refuses anything whose address does not start with 'tst.' — this script can
only ever delete test mailboxes.

TENANT-TOUCHING (CKM-9) — run interactively:
  Connect-ExchangeOnline -UserPrincipalName <admin-upn>
  ./scripts/remove-test-mailbox.ps1 -Suffix demo -Domain tenant-a.example
#>
param(
  [Parameter(Mandatory)][ValidatePattern('^[a-z0-9-]{1,32}$')][string]$Suffix,
  [Parameter(Mandatory)][string]$Domain,
  [switch]$Yes
)
$ErrorActionPreference = 'Stop'
$upn = "tst.$Suffix@$Domain"
if ($upn -notmatch '^tst\.') { throw "refusing: $upn is not a tst.* mailbox" }

Write-Host "Will PERMANENTLY remove shared mailbox $upn"
if (-not $Yes) {
  if ((Read-Host 'Proceed? [y/N]') -notmatch '^[yY]') { exit 1 }
}
Remove-Mailbox -Identity $upn -Confirm:$false
Write-Host "removed $upn"
