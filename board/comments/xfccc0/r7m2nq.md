---
type: comment
at: "2026-11-06T04:30:00Z"
by: "claude"
event: "completed"
---

Merged from Codex card z2k7hm (6 model calls, 113 s). All three
acceptance criteria met: `list_mail_folders` takes `parent` and
`recursive`; `search_messages` gets past the 275 cap by bisecting date
windows and reports a day it cannot split; an archive pull across all
folders needs no raw Graph.

Live, read-only, both delegated tenants: 385 matches in 3 windows on one
(was 275), 5,000 (the limit) in 55 windows and about four minutes on the
other, sorted and without duplicates; recursive folder walks found 20
and 29 folders. Offline 277 passed.

Changed at merge: `hit_max_results` only when something was left
unsearched, and the description now says a folder-scoped search skips
its subfolders and how long big searches take.
