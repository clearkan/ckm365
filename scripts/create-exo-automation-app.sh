#!/usr/bin/env bash
# One-time per-tenant bootstrap of the EXO AUTOMATION app: a dedicated app
# registration that lets scripts (and Jenkins) run Exchange Online
# PowerShell unattended via certificate auth — no user, no MFA prompt.
#
# TENANT-TOUCHING and HIGH-PRIVILEGE: this app gets the
# Office 365 Exchange Online "Exchange.ManageAsApp" application permission
# plus an Entra directory role. That credential is admin-grade for
# Exchange — cert-only, keep the PFX in the Jenkins credential store,
# rotate it, and prefer --role recipient-admin for a CI credential that
# only creates/removes tst.* mailboxes. The full RBAC-for-Applications
# setup (management scopes + role assignments) needs --role exchange-admin.
#
# This is deliberately a SEPARATE app from the ckm365 Graph app: the Graph
# app touches mailbox data under its own scoping; this one administers
# Exchange. Never merge them.
#
# Per tenant (the operator runs this — assigning directory roles is a
# Privileged Role Administrator action and stays human):
#   az login --tenant <tenant-domain> --allow-no-subscriptions
#   ./scripts/create-exo-automation-app.sh --dry-run   # show the plan
#   ./scripts/create-exo-automation-app.sh --yes       # apply
set -euo pipefail

NAME="ckm365-exo-automation"
ROLE="exchange-admin"
CERT_DIR="${HOME}/.config/ckm365/certs"
YES=0
DRY=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --yes|-y) YES=1 ;;
    --dry-run) DRY=1 ;;
    --name) NAME="$2"; shift ;;
    --role) ROLE="$2"; shift ;;
    --cert-dir) CERT_DIR="$2"; shift ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
  shift
done

# Well-known Entra built-in role definition ids (roleTemplateId).
case "${ROLE}" in
  exchange-admin)  ROLE_DEF="29232cdf-9323-42fd-ade2-1d097af3e4de" ;;
  recipient-admin) ROLE_DEF="31392ffb-586c-42d1-9346-e59415a2cc4e" ;;
  *) echo "ERROR: --role must be exchange-admin or recipient-admin" >&2; exit 2 ;;
esac
EXO_SP="00000002-0000-0ff1-ce00-000000000000"  # Office 365 Exchange Online (first-party)

if ! [[ "${NAME}" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$ ]]; then
  echo "ERROR: app display name '${NAME}' contains unsupported characters" >&2
  exit 2
fi

TENANT=$(az account show --query tenantId -o tsv)
UPN=$(az account show --query user.name -o tsv)
ORG=$(az rest --method GET --url "https://graph.microsoft.com/v1.0/organization" \
  --query "value[0].verifiedDomains[?isInitial].name | [0]" -o tsv)
MANAGE_ROLE_ID=$(az ad sp show --id "${EXO_SP}" \
  --query "appRoles[?value=='Exchange.ManageAsApp'].id | [0]" -o tsv)
if [[ -z "${MANAGE_ROLE_ID}" || "${MANAGE_ROLE_ID}" == "None" ]]; then
  echo "ERROR: could not resolve Exchange.ManageAsApp on the EXO service principal" >&2
  exit 1
fi

echo "tenant: ${UPN##*@} (org ${ORG})"
echo "plan: app '${NAME}' + SP; cert (PFX) under ${CERT_DIR};"
echo "      Exchange.ManageAsApp app permission + admin consent (grant-verified);"
echo "      Entra directory role: ${ROLE} (${ROLE_DEF})"
if [[ ${DRY} -eq 1 ]]; then
  echo "DRY RUN — no changes made. Re-run with --yes to apply."
  exit 0
fi
if [[ ${YES} -ne 1 ]]; then
  read -rp "Create the EXO automation app with ADMIN-GRADE rights in this tenant? [y/N] " ok
  [[ "${ok}" == y* ]] || exit 1
fi

# --- app registration (reuse only what we own; see create-app-registration.sh)
APP_ID=$(az ad app list --display-name "${NAME}" --query "[0].appId" -o tsv)
if [[ -n "${APP_ID}" && "${APP_ID}" != "None" ]]; then
  if ! az ad app owner list --id "${APP_ID}" \
      --query "[].userPrincipalName" -o tsv | grep -qix "${UPN}"; then
    echo "ERROR: an app named '${NAME}' exists but ${UPN} is not an owner" >&2
    echo "       — refusing to adopt it. Pick another --name." >&2
    exit 1
  fi
  echo "reusing existing app registration '${NAME}' (ownership verified)"
else
  APP_ID=$(az ad app create --display-name "${NAME}" \
    --sign-in-audience AzureADMyOrg --query appId -o tsv)
  echo "created app registration '${NAME}'"
fi
az ad sp show --id "${APP_ID}" >/dev/null 2>&1 || \
  az ad sp create --id "${APP_ID}" >/dev/null
SP_OBJ=$(az ad sp show --id "${APP_ID}" --query id -o tsv)

# --- certificate (self-signed; PFX for Connect-ExchangeOnline on Linux/CI)
mkdir -p "${CERT_DIR}" && chmod 700 "${CERT_DIR}"
KEY="${CERT_DIR}/${NAME}.key.pem"
CRT="${CERT_DIR}/${NAME}.cert.pem"
PFX="${CERT_DIR}/${NAME}.pfx"
if [[ -f "${PFX}" ]]; then
  echo "reusing existing ${PFX} (delete it first to rotate)"
else
  openssl req -x509 -newkey rsa:2048 -sha256 -days 365 -nodes \
    -keyout "${KEY}" -out "${CRT}" -subj "/CN=${NAME}" 2>/dev/null
  chmod 600 "${KEY}"
  PASS="${CKM365_EXO_PFX_PASSWORD:-$(openssl rand -base64 24)}"
  openssl pkcs12 -export -out "${PFX}" -inkey "${KEY}" -in "${CRT}" \
    -passout "pass:${PASS}"
  chmod 600 "${PFX}"
  if [[ -z "${CKM365_EXO_PFX_PASSWORD:-}" ]]; then
    ( umask 177; printf '%s' "${PASS}" > "${PFX}.pass" )
    echo "generated ${PFX} (password in ${PFX}.pass, 600 — move both into the CI credential store)"
  else
    echo "generated ${PFX} (password taken from CKM365_EXO_PFX_PASSWORD)"
  fi
fi
az ad app credential reset --id "${APP_ID}" --cert "@${CRT}" --append >/dev/null
echo "public cert uploaded to the app registration"

# --- Exchange.ManageAsApp + admin consent, verified against app-role assignments
az ad app update --id "${APP_ID}" --required-resource-accesses \
  "[{\"resourceAppId\":\"${EXO_SP}\",\"resourceAccess\":[{\"id\":\"${MANAGE_ROLE_ID}\",\"type\":\"Role\"}]}]"
EXO_SP_OBJ=$(az ad sp show --id "${EXO_SP}" --query id -o tsv)
CONSENTED=0
for _ in 1 2 3 4 5 6; do
  az ad app permission admin-consent --id "${APP_ID}" >/dev/null 2>&1 || true
  sleep 10
  az rest --method GET --url \
    "https://graph.microsoft.com/v1.0/servicePrincipals/${SP_OBJ}/appRoleAssignments" \
    --query "value[?resourceId=='${EXO_SP_OBJ}'].appRoleId" -o tsv \
    | grep -qx "${MANAGE_ROLE_ID}" && { CONSENTED=1; break; }
done
if [[ ${CONSENTED} -ne 1 ]]; then
  echo "ERROR: Exchange.ManageAsApp consent not verified after retries — re-run" >&2
  exit 1
fi
echo "Exchange.ManageAsApp consented and verified"

# --- Entra directory role (assignment may 400 if it already exists — verify after)
az rest --method POST \
  --url "https://graph.microsoft.com/v1.0/roleManagement/directory/roleAssignments" \
  --body "{\"@odata.type\":\"#microsoft.graph.unifiedRoleAssignment\",\"principalId\":\"${SP_OBJ}\",\"roleDefinitionId\":\"${ROLE_DEF}\",\"directoryScopeId\":\"/\"}" \
  >/dev/null 2>&1 || true
COUNT=$(az rest --method GET --url \
  "https://graph.microsoft.com/v1.0/roleManagement/directory/roleAssignments?\$filter=principalId eq '${SP_OBJ}' and roleDefinitionId eq '${ROLE_DEF}'" \
  --query "length(value)" -o tsv)
if [[ "${COUNT}" == "0" ]]; then
  echo "ERROR: directory role assignment not present after attempt" >&2
  exit 1
fi
echo "directory role '${ROLE}' assigned and verified"

echo
echo "unattended EXO auth is ready — env for scripts/Jenkins:"
echo "  export CKM365_EXO_APP_ID=${APP_ID}"
echo "  export CKM365_EXO_ORG=${ORG}"
echo "  export CKM365_EXO_PFX_PATH=${PFX}"
echo "  export CKM365_EXO_PFX_PASSWORD_FILE=${PFX}.pass   # or CKM365_EXO_PFX_PASSWORD"
echo "next: pwsh ./scripts/setup-app-rbac.ps1 ... (dry-run by default)"
