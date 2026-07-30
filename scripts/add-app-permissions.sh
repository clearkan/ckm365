#!/usr/bin/env bash
# Add APPLICATION permissions (Mail.ReadWrite + Calendars.ReadWrite) to an
# EXISTING ckm365 app registration for app-only / client-credential mode
# (CKM-5), then admin-consent and verify against actual app-role
# assignments on the service principal.
#
# TENANT-TOUCHING and SAFETY-ORDERED: an application permission is
# TENANT-WIDE (every mailbox) from the moment it is consented. Create the
# Exchange RBAC-for-Applications management scope BEFORE running this (or
# in the same interactive sitting, consent last) — see
# docs/app-only-setup.md, and never verify app-only credentials while the
# grant is unscoped.
#
# CAUTION (union semantics): Microsoft documents Exchange access as the
# UNION of Entra app-role grants and Exchange RBAC role assignments — a
# consented tenant-wide app role is NOT narrowed by a management scope.
# If the out-of-scope NEGATIVE test in docs/app-only-setup.md does not
# 403/404, remove the app-role consent and use the RBAC-only path (skip
# this script; grant via New-ManagementRoleAssignment alone).
#
# Per tenant:
#   az login --tenant <tenant-domain> --allow-no-subscriptions
#   ./scripts/add-app-permissions.sh --dry-run   # show the plan
#   ./scripts/add-app-permissions.sh --yes       # apply
#
# The app is located via the client_id recorded in profiles.toml for the
# signed-in tenant's profile (never by display name — see security review).
# Existing delegated scopes are PRESERVED: the current requiredResourceAccess
# is read and merged, never replaced wholesale.
set -euo pipefail

YES=0
DRY=0
PROFILE=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --yes|-y) YES=1 ;;
    --dry-run) DRY=1 ;;
    --profile) PROFILE="$2"; shift ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
  shift
done

GRAPH_SP="00000003-0000-0000-c000-000000000000"
ROLES=(Mail.ReadWrite Calendars.ReadWrite)  # application (role-type), not scope-type

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

# Resolve role ids from Graph's appRoles (NOT oauth2PermissionScopes).
declare -A ROLE_IDS
for role in "${ROLES[@]}"; do
  ID=$(az ad sp show --id "${GRAPH_SP}" \
    --query "appRoles[?value=='${role}'].id | [0]" -o tsv)
  if [[ -z "${ID}" || "${ID}" == "None" ]]; then
    echo "ERROR: could not resolve application role '${role}'" >&2
    exit 1
  fi
  ROLE_IDS[$role]="${ID}"
done

echo "tenant domain: ${DOMAIN} -> profile '${PROFILE}' (app from profiles.toml)"
echo "will declare application roles: ${ROLES[*]} (existing delegated scopes kept)"
echo "then admin-consent and verify against the SP's appRoleAssignments"
if [[ ${DRY} -eq 1 ]]; then
  echo "DRY RUN — no changes made. Re-run with --yes to apply."
  exit 0
fi
if [[ ${YES} -ne 1 ]]; then
  read -rp "Grant TENANT-WIDE application permissions in this tenant? (RBAC scope in place?) [y/N] " ok
  [[ "${ok}" == y* ]] || exit 1
fi

# Merge the roles into the app's existing Graph resourceAccess — an update
# here REPLACES requiredResourceAccess, so rebuild it from what is there.
CURRENT=$(az ad app show --id "${APP_ID}" --query "requiredResourceAccess" -o json)
MERGED=$(CURRENT_JSON="${CURRENT}" python3 - "$GRAPH_SP" "${ROLE_IDS[@]}" <<'PY'
import json, os, sys
graph_sp, role_ids = sys.argv[1], sys.argv[2:]
req = json.loads(os.environ["CURRENT_JSON"])
graph = next((r for r in req if r["resourceAppId"] == graph_sp), None)
if graph is None:
    graph = {"resourceAppId": graph_sp, "resourceAccess": []}
    req.append(graph)
have = {a["id"] for a in graph["resourceAccess"]}
graph["resourceAccess"] += [{"id": rid, "type": "Role"}
                            for rid in role_ids if rid not in have]
print(json.dumps(req))
PY
)
az ad app update --id "${APP_ID}" --required-resource-accesses "${MERGED}"
echo "declared ${#ROLES[@]} application permissions (delegated scopes preserved)"

# Consent verified against actual app-role assignments — application
# permissions do NOT appear in oauth2 permission grants, and consent right
# after a permission update can record a stale set and still exit 0 (see
# create-app-registration.sh).
SP_ID=$(az ad sp show --id "${APP_ID}" --query id -o tsv)
GRAPH_SP_OBJ=$(az ad sp show --id "${GRAPH_SP}" --query id -o tsv)
CONSENTED=0
for _ in 1 2 3 4 5 6; do
  az ad app permission admin-consent --id "${APP_ID}" >/dev/null 2>&1 || true
  sleep 10
  ASSIGNED=$(az rest --method GET --url \
    "https://graph.microsoft.com/v1.0/servicePrincipals/${SP_ID}/appRoleAssignments" \
    --query "value[?resourceId=='${GRAPH_SP_OBJ}'].appRoleId" -o tsv)
  MISSING=0
  for role in "${ROLES[@]}"; do
    grep -qx "${ROLE_IDS[$role]}" <<<"${ASSIGNED}" || { MISSING=1; break; }
  done
  if [[ ${MISSING} -eq 0 ]]; then
    CONSENTED=1
    break
  fi
done
if [[ ${CONSENTED} -eq 1 ]]; then
  echo "admin consent granted and verified against app-role assignments"
  echo "next: docs/app-only-setup.md — certificate credential, then the"
  echo "      out-of-scope NEGATIVE test before any real use"
else
  echo "WARNING: app-role assignments still incomplete after retries — re-run" >&2
  exit 1
fi
