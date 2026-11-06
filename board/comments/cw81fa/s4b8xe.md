---
type: comment
at: "2026-11-06T04:30:00Z"
by: "claude"
event: "started"
---

Codex card v6n4tj, spec `tests/test_mail_exclusions.py`. Three changes
from the proposal, each to keep to the repo's rules:

- The list is TOML, not YAML: stdlib `tomllib` reads it, and core
  dependencies stay httpx and msal. Same entry fields as proposed.
- A per-call `exclusions_file` exists only on `check_recipients`. Draft
  tools and `send_draft` use the profile's file, so a project that wants
  its own list points the profile at it. That keeps five tool
  signatures unchanged.
- A configured list that is missing or invalid is an error raised before
  any Graph call, on every tool. A list that silently fails to load
  protects nobody.
