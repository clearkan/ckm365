---
type: "issue"
title: "Ship the PEP 561 py.typed marker (verified present in the wheel)"
created: "2026-07-30T14:39:43Z"
resource: "oif:ckm/2twggd"
aliases: ["CKM-23"]
kind: "improvement"
priority: "medium"
assignees: ["claude"]
requested_by: "human:seanwy"
tags: ["clearkan", "packaging", "typing"]
---

ClearKan follow-up ask B: the package is fully annotated but has no
py.typed, so consumer type checkers treat every ckm365 import as Any.

- Add empty src/ckm365/py.typed.
- uv build and CONFIRM the marker is inside the wheel (hatchling
  usually includes it automatically; the silent-omission failure mode
  is the thing to check). Add force-include only if needed.
