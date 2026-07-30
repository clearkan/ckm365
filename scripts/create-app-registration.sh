#!/usr/bin/env bash
# Create (or reuse) the dedicated ckm365 app registration in the signed-in
# tenant, grant delegated Graph permissions, attempt admin consent, and
# append a matching profile to profiles.toml. Idempotent — safe to re-run.
#
# TENANT-TOUCHING (CKM-4). Per tenant:
#   az login --tenant <tenant-domain> --allow-no-subscriptions
#   ./scripts/create-app-registration.sh --yes
#
# Prints status only — no app ids, tenant ids, or tokens on stdout; the
# identifiers land directly in the profiles file.
set -euo pipefail

NAME="ckm365-graph"
PROFILE=""
YES=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --yes|-y) YES=1 ;;
    --name) NAME="$2"; shift ;;
    --profile) PROFILE="$2"; shift ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
  shift
done

GRAPH_SP="00000003-0000-0000-c000-000000000000" # Microsoft Graph (well-known)
SCOPES=(
  Mail.Read Mail.Read.Shared Mail.ReadWrite Mail.ReadWrite.Shared
  Calendars.Read Calendars.Read.Shared Calendars.ReadWrite Calendars.ReadWrite.Shared
  offline_access
)

TENANT=$(az account show --query tenantId -o tsv)
UPN=$(az account show --query user.name -o tsv)
DOMAIN="${UPN##*@}"
PROFILE="${PROFILE:-${DOMAIN%%.*}}"
PROFILES_FILE="${CKM365_PROFILES:-$HOME/.config/ckm365/profiles.toml}"

# Match the loader's profile-name rule up front, and keep NAME sane — both
# are interpolated into TOML/az arguments.
if ! [[ "${PROFILE}" =~ ^[a-z0-9][a-z0-9_-]*$ ]]; then
  echo "ERROR: profile name '${PROFILE}' must match [a-z0-9][a-z0-9_-]*" >&2
  exit 2
fi
if ! [[ "${NAME}" =~ ^[A-Za-z0-9][A-Za-z0-9\ ._-]{0,63}$ ]]; then
  echo "ERROR: app display name '${NAME}' contains unsupported characters" >&2
  exit 2
fi

echo "signed-in tenant domain: ${DOMAIN} -> profile '${PROFILE}'"
if [[ ${YES} -ne 1 ]]; then
  read -rp "Proceed in this tenant? [y/N] " ok
  [[ "${ok}" == y* ]] || exit 1
fi

# Create or reuse the app registration (public client for device-code flow).
# Display names are NOT unique: before adopting (and admin-consenting!) an
# existing app, require it to match the recorded profile client_id, or —
# with no profile recorded — require the signed-in user to be an owner.
APP_ID=$(az ad app list --display-name "${NAME}" --query "[0].appId" -o tsv)
if [[ -n "${APP_ID}" && "${APP_ID}" != "None" ]]; then
  RECORDED=$(awk -v p="[profiles.${PROFILE}]" '
    $0 == p {insec=1; next}
    /^\[/ {insec=0}
    insec && $1 == "client_id" {gsub(/"/, "", $3); print $3; exit}
  ' "${PROFILES_FILE}" 2>/dev/null || true)
  if [[ -n "${RECORDED}" && "${RECORDED}" != "${APP_ID}" ]]; then
    echo "ERROR: an app named '${NAME}' exists but does not match the" >&2
    echo "       client_id recorded for profile '${PROFILE}' — refusing" >&2
    echo "       to adopt it. Investigate before re-running." >&2
    exit 1
  fi
  if [[ -z "${RECORDED}" ]] && ! az ad app owner list --id "${APP_ID}" \
      --query "[].userPrincipalName" -o tsv | grep -qix "${UPN}"; then
    echo "ERROR: an app named '${NAME}' exists but ${UPN} is not an owner" >&2
    echo "       — refusing to adopt/consent it. Pick another --name." >&2
    exit 1
  fi
  echo "reusing existing app registration '${NAME}' (ownership verified)"
else
  APP_ID=$(az ad app create \
    --display-name "${NAME}" \
    --sign-in-audience AzureADMyOrg \
    --is-fallback-public-client true \
    --query appId -o tsv)
  echo "created app registration '${NAME}'"
fi

# Declare the delegated Graph permissions declaratively (idempotent).
ACCESS=""
for scope in "${SCOPES[@]}"; do
  ID=$(az ad sp show --id "${GRAPH_SP}" \
    --query "oauth2PermissionScopes[?value=='${scope}'].id | [0]" -o tsv)
  if [[ -z "${ID}" || "${ID}" == "None" ]]; then
    echo "WARNING: could not resolve scope '${scope}'" >&2
    continue
  fi
  ACCESS+="{\"id\":\"${ID}\",\"type\":\"Scope\"},"
done
az ad app update --id "${APP_ID}" --required-resource-accesses \
  "[{\"resourceAppId\":\"${GRAPH_SP}\",\"resourceAccess\":[${ACCESS%,}]}]"
echo "declared ${#SCOPES[@]} delegated Graph permissions"

# Service principal + admin consent. A consent issued right after the
# permission update can record a stale/partial permission set and still exit
# 0 (bit us on tenant-a: login worked, RO-scope refresh died with AADSTS65001),
# so success is defined by the GRANTS actually containing every scope —
# re-consent and re-check until they do.
az ad sp show --id "${APP_ID}" >/dev/null 2>&1 || \
  az ad sp create --id "${APP_ID}" >/dev/null
CONSENTED=0
for _ in 1 2 3 4 5 6; do
  az ad app permission admin-consent --id "${APP_ID}" >/dev/null 2>&1 || true
  sleep 10
  GRANTED=$(az ad app permission list-grants --id "${APP_ID}" \
    --query "[].scope" -o tsv | tr ' \t' '\n')
  MISSING=0
  for scope in "${SCOPES[@]}"; do
    grep -qx "${scope}" <<<"${GRANTED}" || { MISSING=1; break; }
  done
  if [[ ${MISSING} -eq 0 ]]; then
    CONSENTED=1
    break
  fi
done
if [[ ${CONSENTED} -eq 1 ]]; then
  echo "admin consent granted and verified against grants"
else
  echo "WARNING: grants still incomplete after retries — re-run this script later" >&2
fi

# Append the profile (never clobber an existing entry).
mkdir -p "$(dirname "${PROFILES_FILE}")"
if grep -qs "^\[profiles\.${PROFILE}\]" "${PROFILES_FILE}"; then
  echo "profile '${PROFILE}' already present in ${PROFILES_FILE} — left untouched"
else
  [[ -f "${PROFILES_FILE}" ]] || install -m 600 /dev/null "${PROFILES_FILE}"
  cat >> "${PROFILES_FILE}" <<EOF

[profiles.${PROFILE}]
tenant_id = "${TENANT}"
client_id = "${APP_ID}"
auth = "device_code"
EOF
  chmod 600 "${PROFILES_FILE}"
  echo "profile '${PROFILE}' appended to ${PROFILES_FILE}"
fi

echo "next: uv run ckm365 login ${PROFILE}"
