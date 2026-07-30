#!/usr/bin/env bash
# Add the Mail.Send + Mail.Send.Shared delegated scopes to an EXISTING
# ckm365 app registration and re-grant verified admin consent.
#
# TENANT-TOUCHING and a DELIBERATE opt-in: send consent is intentionally not
# part of create-app-registration.sh, so enabling send is an explicit,
# per-tenant decision. Per tenant:
#   az login --tenant <tenant-domain> --allow-no-subscriptions
#   ./scripts/add-send-scopes.sh --yes
#
# The app is located via the client_id recorded in profiles.toml for the
# signed-in tenant's profile (never by display name — see security review).
set -euo pipefail

YES=0
PROFILE=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --yes|-y) YES=1 ;;
    --profile) PROFILE="$2"; shift ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
  shift
done

GRAPH_SP="00000003-0000-0000-c000-000000000000"
SCOPES=(
  Mail.Read Mail.Read.Shared Mail.ReadWrite Mail.ReadWrite.Shared
  Calendars.Read Calendars.Read.Shared Calendars.ReadWrite Calendars.ReadWrite.Shared
  offline_access
  Mail.Send Mail.Send.Shared
)

UPN=$(az account show --query user.name -o tsv)
DOMAIN="${UPN##*@}"
PROFILE="${PROFILE:-${DOMAIN%%.*}}"
PROFILES_FILE="${CKM365_PROFILES:-$HOME/.config/ckm365/profiles.toml}"

if ! [[ "${PROFILE}" =~ ^[a-z0-9][a-z0-9_-]*$ ]]; then
  echo "ERROR: profile name '${PROFILE}' must match [a-z0-9][a-z0-9_-]*" >&2
  exit 2
fi

APP_ID=$(awk -v p="[profiles.${PROFILE}]" '
  $0 == p {insec=1; next}
  /^\[/ {insec=0}
  insec && $1 == "client_id" {gsub(/"/, "", $3); print $3; exit}
' "${PROFILES_FILE}")
if [[ -z "${APP_ID}" ]]; then
  echo "ERROR: no client_id for profile '${PROFILE}' in ${PROFILES_FILE}" >&2
  echo "       run scripts/create-app-registration.sh first" >&2
  exit 1
fi

echo "tenant domain: ${DOMAIN} -> profile '${PROFILE}' (app from profiles.toml)"
if [[ ${YES} -ne 1 ]]; then
  read -rp "Add Mail.Send scopes + admin consent in this tenant? [y/N] " ok
  [[ "${ok}" == y* ]] || exit 1
fi

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
echo "declared ${#SCOPES[@]} delegated Graph permissions (incl. send)"

# Consent verified against actual grants (see create-app-registration.sh
# for why exit-code success is not trusted).
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
  echo "admin consent granted and verified (send scopes included)"
  echo "next: no re-login needed — the cached refresh token can now mint"
  echo "      send-scoped tokens when the server runs with --enable-send"
else
  echo "WARNING: grants still incomplete after retries — re-run this script" >&2
  exit 1
fi
