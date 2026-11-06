---
type: comment
resource: oif:ckm/r8m2qx/k3w8vb
at: '2026-11-07T00:30:00+00:00'
by: claude
---

Merged. The 8 failures were a spec bug (exact encoded path vs httpx's
decoded `/v1.0/...` path); fixed on main, Codex's code passed unchanged:
393 passed. One tweak at merge: master-category names read with
`.get("displayName")` so a nameless entry cannot raise.
