---
type: "issue"
title: "Phase 0 — propose module layout + helper signatures for approval"
created: "2026-07-29T21:47:41Z"
resource: "oif:ckm/8nd03y"
aliases: ["CKM-3"]
kind: "task"
priority: "high"
assignees: ["claude"]
requested_by: "human:seanwy"
tags: ["phase-0", "design"]
depends_on: ["xcaz34"]
depends_on_aliases: ["CKM-2"]
---

From the reference study, propose the abstraction layer BEFORE writing
tools: thin graph.py (httpx client, auth header injection, pagination
helper, retry/backoff on 429/503, consistent error mapping) and auth.py
(MSAL wrapper, tenant-pinned authority — never `common`). Show module
layout and helper signatures to seanwy for approval before implementing
tool modules. Flag ClearKan patterns worth lifting.
