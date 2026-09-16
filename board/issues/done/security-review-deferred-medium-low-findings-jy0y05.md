---
type: "issue"
title: "Security review — deferred medium/low findings (Fable 5 review 2026-07-30)"
created: "2026-07-29T23:40:54Z"
resource: "oif:ckm/jy0y05"
aliases: ["CKM-15"]
kind: "task"
priority: "medium"
requested_by: "human:seanwy"
tags: ["security", "review"]
---

HIGHs fixed immediately (account-pin enforcement + schema drop; calendar
attendee writes made send-tier; full send tier: DELEGATED_SEND scopes,
SEND registry, require_send, destructive_hint annotations, consent via
scripts/add-send-scopes.sh located by client_id not display name).
Deferred items — several are <5-line fixes, good for one hardening pass:

MEDIUM
- MSAL cache: no cross-process lock; fcntl.flock sidecar around
  reload->acquire->persist (RT rotation clobber under concurrency)
- paged(): pin @odata.nextLink host to GRAPH_BASE before following
  (bearer goes wherever the link points today) — ~2 lines
- calendar timezone param: validate before Prefer-header interpolation
  (quote-escape can smuggle preference tokens) — ~3 lines
- create-app-registration.sh: on app reuse, verify ownership/known
  client_id before admin-consent (display-name adoption attack);
  add-send-scopes.sh already resolves via profiles.toml client_id
- add_attachment: optional CKM365_ATTACH_ROOT path constraint
  (resolve + is_relative_to); file_path audit-logging DONE
- auth: refuse/clean multiple cached accounts per profile cache
  (accounts[0] nondeterminism -> wrong-identity calls within tenant)

LOW
- If-Match/etag on draft PATCHes (check-then-act race until Dec 2026
  Graph enforcement)
- state_dir/cache_dir: chmod 0700 when pre-existing, not only at create
- $search: escape quotes/backslash instead of replacing quotes
- registration script: validate PROFILE/NAME charset; umask before
  profiles.toml create; quoting in printed re-run hint
- README: document that the cached RT is always RW-capable (read-only
  mode shrinks live tokens, not stolen-cache blast radius) — send tier
  deliberately kept out of the default consent set (implemented)
