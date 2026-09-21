---
type: comment
at: "2026-09-21T00:00:00Z"
by: "claude"
event: "created"
---

Imported on seanwy's go-ahead. Changes from the bundle:
- a generic default display name
- a `--check` dependency report in place of the self-installing pip/apt steps
- the script writes its own pid (the xvfb-run wrapper's pid never reached python) and flushes on SIGTERM
- no caption text in `capture.log`
- the chat consent notice with an opt-out
- a rule never to commit meeting output to a public repo

Nothing has run against a live meeting yet.
