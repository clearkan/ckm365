#!/usr/bin/env bash
# Add the READ-ONLY Teams discovery scopes to an EXISTING ckm365 app
# registration and re-grant verified admin consent (CKM-25).
#
# TENANT-TOUCHING and a DELIBERATE opt-in, exactly like add-send-scopes.sh:
# Teams consent is NEVER folded into the mailbox scopes, so a mail
# `--write` server flag can never imply the ability to enumerate Teams.
# Scopes added (all read-only, least privilege for discovery):
#   Team.ReadBasic.All            list teams (id/name/archived)
#   Channel.ReadBasic.All         list a team's channels
#   TeamsAppInstallation.ReadForTeam   list apps installed in a team
#
# DELEGATED only, on purpose. The app-only equivalents are tenant-wide:
# Exchange RBAC-for-Applications scoping does NOT cover Teams, so an
# app-only Team.ReadBasic.All reads EVERY team in the tenant. If a
# headless caller genuinely needs Teams, scope it per team with Teams
# resource-specific consent (RSC) instead of running this script with
# application permissions.
#
# Existing scopes are PRESERVED: the current requiredResourceAccess is
# read and merged, never replaced.
#
# Per tenant:
#   az login --tenant <tenant-domain> --allow-no-subscriptions
#   ./scripts/add-teams-scopes.sh --dry-run   # show the plan
#   ./scripts/add-teams-scopes.sh --yes       # apply
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
SCOPES=(Team.ReadBasic.All Channel.ReadBasic.All TeamsAppInstallation.ReadForTeam)

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

declare -A SCOPE_IDS
for scope in "${SCOPES[@]}"; do
  ID=$(az ad sp show --id "${GRAPH_SP}" \
    --query "oauth2PermissionScopes[?value=='${scope}'].id | [0]" -o tsv)
  if [[ -z "${ID}" || "${ID}" == "None" ]]; then
    echo "ERROR: could not resolve delegated scope '${scope}'" >&2
    exit 1
  fi
  SCOPE_IDS[$scope]="${ID}"
done

echo "tenant domain: ${DOMAIN} -> profile '${PROFILE}' (app from profiles.toml)"
echo "will ADD delegated read-only Teams scopes: ${SCOPES[*]}"
echo "existing mail/calendar scopes are preserved (merge, not replace)"
if [[ ${DRY} -eq 1 ]]; then
  echo "DRY RUN — no changes made. Re-run with --yes to apply."
  exit 0
fi
if [[ ${YES} -ne 1 ]]; then
  read -rp "Add Teams discovery scopes + admin consent in this tenant? [y/N] " ok
  [[ "${ok}" == y* ]] || exit 1
fi

CURRENT=$(az ad app show --id "${APP_ID}" --query "requiredResourceAccess" -o json)
MERGED=$(CURRENT_JSON="${CURRENT}" python3 - "$GRAPH_SP" "${SCOPE_IDS[@]}" <<'PY'
import json, os, sys
graph_sp, scope_ids = sys.argv[1], sys.argv[2:]
req = json.loads(os.environ["CURRENT_JSON"])
graph = next((r for r in req if r["resourceAppId"] == graph_sp), None)
if graph is None:
    graph = {"resourceAppId": graph_sp, "resourceAccess": []}
    req.append(graph)
have = {a["id"] for a in graph["resourceAccess"]}
graph["resourceAccess"] += [{"id": sid, "type": "Scope"}
                            for sid in scope_ids if sid not in have]
print(json.dumps(req))
PY
)
az ad app update --id "${APP_ID}" --required-resource-accesses "${MERGED}"
echo "declared ${#SCOPES[@]} delegated Teams permissions (existing scopes kept)"

# Consent verified against actual grants — a consent issued right after a
# permission update can record a stale set and still exit 0 (see
# create-app-registration.sh for the incident this policy came from).
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
  echo "admin consent granted and verified (Teams discovery scopes included)"
  echo "next: uv run ckm365 login ${PROFILE}   # re-login to pick up the new scopes"
  echo "      uv run python scripts/live-smoke.py ${PROFILE} --teams"
else
  echo "WARNING: grants still incomplete after retries — re-run this script" >&2
  exit 1
fi
