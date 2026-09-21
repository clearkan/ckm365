---
type: "issue"
title: "set_categories tool — add/remove Outlook categories on messages"
created: "2026-09-21T00:00:00Z"
resource: "oif:ckm/g669gd"
aliases: ["CKM-51"]
kind: "feature"
priority: "medium"
requested_by: "human:seanwy"
tags: ["mail", "triage", "write-tier"]
---

Requested from another agent session working for seanwy: tag every email
whose content has been filed into a git repo with an "In git" category.
With no tool for it, that session used the graph-direct escape hatch
(throwaway `tmp/tag_in_git.py`, write=True, seanwy's OK) and tagged 12
messages. The escape hatch did the job, but the need will come up again.

Proposed shape: `set_categories(message_ids, add=[...], remove=[...])`,
in `tools/mail/triage.py` alongside mark_read/flag, write tier,
batched through the existing `batch_ids`/`apply_each` convention.

Notes for the implementer:
- `categories` PATCH **replaces** the whole array, so add/remove is a
  batched GET (`$select=categories`), then a batched PATCH of the merged
  list. Skip the PATCH when nothing changes. Last write wins if Outlook edits
  the categories in between. Accept that and document it.
- Create a missing master category (POST `outlook/masterCategories`)
  for names in `add`. The script did this with preset7 under the current
  consent. Check which scope it actually rode on (MailboxSettings.ReadWrite
  or not), and degrade to "applied, but no master entry (so no colour)"
  rather than failing if the scope is missing.
- Metadata-only PATCH on a non-draft, the same class as isRead/flag. It
  doesn't cut against the draft-only rule, which governs content.
- Remove `tmp/tag_in_git.py` once the tool lands.
