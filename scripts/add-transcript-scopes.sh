#!/usr/bin/env bash
# Add the READ-ONLY meeting-transcript scopes to an EXISTING ckm365 app
# registration and re-grant verified admin consent (CKM-30).
#
# TENANT-TOUCHING and a DELIBERATE opt-in, like add-send-scopes.sh and
# add-teams-scopes.sh. Transcripts are meeting CONTENT — treat this tier
# with the same care as mail bodies: never logged, never printed.
#   OnlineMeetings.Read                 resolve a meeting from its join URL
#   OnlineMeetingTranscript.Read.All    read transcripts of meetings the
#                                       signed-in user organised OR is on
#                                       the calendar invite for
#
# Both are DELEGATED. Note OnlineMeetingTranscript.Read.All is
# admin-consent-required BY DEFINITION — no tenant setting ever opens it
# to user consent. In tenants we do not administer, this is the one-click
# ask documented in CKM-31, not something a user can self-serve.
#
# Existing scopes are PRESERVED: the current requiredResourceAccess is
# read and merged, never replaced.
#
# (If a fourth opt-in tier ever appears, generalise these three sibling
# scripts into one parameterised by scope set — three is still readable.)
#
# Per tenant:
#   az login --tenant <tenant-domain> --allow-no-subscriptions
#   ./scripts/add-transcript-scopes.sh --dry-run   # show the plan
#   ./scripts/add-transcript-scopes.sh --yes       # apply
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
SCOPES=(OnlineMeetings.Read OnlineMeetingTranscript.Read.All)

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
echo "will ADD delegated read-only transcript scopes: ${SCOPES[*]}"
echo "existing mail/calendar/teams scopes are preserved (merge, not replace)"
if [[ ${DRY} -eq 1 ]]; then
  echo "DRY RUN — no changes made. Re-run with --yes to apply."
  exit 0
fi
if [[ ${YES} -ne 1 ]]; then
  read -rp "Add transcript scopes + admin consent in this tenant? [y/N] " ok
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
echo "declared ${#SCOPES[@]} delegated transcript permissions (existing scopes kept)"

# Consent verified against actual grants — exit-code success is not trusted
# here (see create-app-registration.sh for the incident behind that rule).
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
  echo "admin consent granted and verified (transcript scopes included)"
  echo "ALSO REQUIRED: the Teams admin setting 'Graph API access to"
  echo "  transcripts' must be ON, or the API 403s even with consent."
  echo "next: uv run ckm365 login ${PROFILE}   # re-login to pick up the scopes"
else
  echo "WARNING: grants still incomplete after retries — re-run this script" >&2
  exit 1
fi
