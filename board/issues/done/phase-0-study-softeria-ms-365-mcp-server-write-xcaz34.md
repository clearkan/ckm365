---
type: "issue"
title: "Phase 0 — study Softeria ms-365-mcp-server, write docs/reference-notes.md"
created: "2026-07-29T21:47:41Z"
resource: "oif:ckm/xcaz34"
aliases: ["CKM-2"]
kind: "task"
priority: "high"
assignees: ["claude"]
requested_by: "human:seanwy"
tags: ["phase-0", "research"]
---

Clone https://github.com/Softeria/ms-365-mcp-server into ./tmp/softeria-ref/
(git-ignored; delete when phase 1 completes). Study and write up concisely
in docs/reference-notes.md:

- Graph call shapes for mail, calendar, auth — endpoints, pagination,
  429/throttling handling, body/HTML handling
- Tool naming, parameter schemas, preset/category system (--preset mail)
- Token caching (OS credential store with file fallback) — replicate
- What it over-complicates or gets wrong, to avoid

Reference only — no dependence, no vendored code (MIT, studied not copied).
