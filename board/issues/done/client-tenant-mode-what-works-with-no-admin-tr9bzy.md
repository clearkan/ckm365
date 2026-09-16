---
type: "issue"
title: "Client-tenant mode — what works with NO admin rights (guest or member)"
created: "2026-08-01T03:54:51Z"
resource: "oif:ckm/tr9bzy"
aliases: ["CKM-29"]
kind: "task"
priority: "high"
requested_by: "human:seanwy"
tags: ["auth", "client-tenant", "research", "constraint"]
---

ARCHITECTURAL CONSTRAINT, newly surfaced by seanwy (2026-08-01), and it
invalidates an assumption baked into every setup path we have.

Everything built so far assumes we control the tenant: create an app
registration, grant admin consent, assign Exchange RBAC, create
mailboxes. That holds for our OWN tenants. It does NOT hold for client
tenants, which are the actual reason M365 support exists.

In client tenants seanwy is:
- a GUEST (B2B) in one (placeholder: client-a.example), and
- a regular licensed MEMBER in another (placeholder: client-b.example),
with NO ADMIN RIGHTS in either. He cannot register apps, cannot grant
admin consent, cannot touch Exchange RBAC, cannot create mailboxes.

So the whole scripts/create-app-registration.sh + admin-consent +
RBAC pipeline is unavailable there. Whatever we support in client
tenants is gated to what one non-admin identity can do.

WHAT THIS ISSUE MUST ESTABLISH (research first, code second):
- Which Graph scopes are USER-consentable vs admin-consent-required for
  the capabilities we care about (mail, calendar, chat, meetings,
  transcripts, files). Note the 2026 default tenant setting only allows
  user consent for verified-publisher apps and low-impact permissions —
  many tenants disable user consent entirely.
- Whether a MULTI-TENANT app registered in OUR tenant can be
  user-consented into a client tenant, and what that requires
  (verified publisher? tenant consent settings?).
- What a GUEST identity can actually reach — guests are far more
  restricted than members and much of Graph is closed to them by
  default. Establish the realistic floor.
- Whether ANY of it survives without an admin ever being involved, or
  whether the honest answer is "one small admin ask per client tenant",
  in which case: what is the MINIMUM ask, phrased so a client admin
  will approve it?

Gates CKM-30 (transcripts) and any future client-tenant capability.
Deliverable is a decision doc + a documented client-tenant setup path,
NOT new tool surface until the floor is known.
