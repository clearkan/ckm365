#Requires -Modules ExchangeOnlineManagement
<#
Create a tst.<suffix> shared test mailbox (no license cost) and grant the
operator FullAccess + SendAs, ready for tests/test_live.py.

TENANT-TOUCHING (CKM-9) — run interactively:
  Connect-ExchangeOnline -UserPrincipalName <admin-upn>
  ./scripts/create-test-mailbox.ps1 -Suffix demo -Domain tenant-a.example `
      -Grantee operator@tenant-a.example
#>
param(
  [Parameter(Mandatory)][ValidatePattern('^[a-z0-9-]{1,32}$')][string]$Suffix,
  [Parameter(Mandatory)][string]$Domain,
  [Parameter(Mandatory)][string]$Grantee,
  [switch]$Yes
)
$ErrorActionPreference = 'Stop'
$upn = "tst.$Suffix@$Domain"

Write-Host "Will create shared mailbox $upn and grant $Grantee FullAccess + SendAs"
if (-not $Yes) {
  if ((Read-Host 'Proceed? [y/N]') -notmatch '^[yY]') { exit 1 }
}

New-Mailbox -Shared -Name "tst.$Suffix" -DisplayName "ckm365 test $Suffix" `
  -PrimarySmtpAddress $upn | Out-Null
Add-MailboxPermission -Identity $upn -User $Grantee `
  -AccessRights FullAccess -AutoMapping:$false | Out-Null
Add-RecipientPermission -Identity $upn -Trustee $Grantee `
  -AccessRights SendAs -Confirm:$false | Out-Null

Write-Host "created $upn"
Write-Host "next: CKM365_LIVE_ACCOUNT=<profile> CKM365_LIVE_MAILBOX=$upn \"
Write-Host "        uv run pytest tests/test_live.py -q"
