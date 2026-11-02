---
type: comment
at: "2026-11-02T05:30:00Z"
by: "claude"
event: "started"
---

Taken as one Codex card, q4m8vd, test-first. The spec is
`tests/test_mail_migrate_notes.py` (22 tests, skipped until the planner
knows `note`). All four classification rules from this issue are in it,
and the thread-record answer is the documented convention, not nested
parsing: the planner reads top-level keys only and stays free of a YAML
dependency.

Two existing tests used a bare note as their example of `manual`. They
now use cases that stay manual under the new rules: a note beside a
same-stem `.eml`, and a mail record with no id.

The pair destination for a taken `<stem>.md` is out of scope here; it
needs a naming decision.
