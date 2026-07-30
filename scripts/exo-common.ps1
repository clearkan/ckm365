# Shared Exchange Online connection helper — dot-source, then Connect-Ckm365Exo.
#
# Unattended (CI/Jenkins) when the env vars from create-exo-automation-app.sh
# are set:
#   CKM365_EXO_APP_ID            automation app client id
#   CKM365_EXO_ORG               tenant's initial .onmicrosoft.com domain
#   CKM365_EXO_PFX_PATH          certificate PFX path
#   CKM365_EXO_PFX_PASSWORD      PFX password (or _FILE pointing at a 600 file)
# Falls back to interactive browser auth otherwise. No-op if already connected.

function Connect-Ckm365Exo {
  param([string]$UserPrincipalName)
  if (Get-ConnectionInformation) { return }
  if ($env:CKM365_EXO_APP_ID) {
    $pw = $env:CKM365_EXO_PFX_PASSWORD
    if (-not $pw -and $env:CKM365_EXO_PFX_PASSWORD_FILE) {
      $pw = (Get-Content -Raw $env:CKM365_EXO_PFX_PASSWORD_FILE).Trim()
    }
    if (-not ($env:CKM365_EXO_ORG -and $env:CKM365_EXO_PFX_PATH -and $pw)) {
      throw 'CKM365_EXO_APP_ID is set but ORG/PFX_PATH/PFX_PASSWORD(_FILE) are incomplete'
    }
    Connect-ExchangeOnline -AppId $env:CKM365_EXO_APP_ID `
      -Organization $env:CKM365_EXO_ORG `
      -CertificateFilePath $env:CKM365_EXO_PFX_PATH `
      -CertificatePassword (ConvertTo-SecureString -String $pw -AsPlainText -Force) `
      -ShowBanner:$false
  }
  elseif ($UserPrincipalName) {
    Connect-ExchangeOnline -UserPrincipalName $UserPrincipalName -ShowBanner:$false
  }
  else {
    Connect-ExchangeOnline -ShowBanner:$false
  }
}
