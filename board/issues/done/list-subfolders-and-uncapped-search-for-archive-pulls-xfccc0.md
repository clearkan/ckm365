---
type: issue
resource: oif:ckm/xfccc0
title: Tools can't list mail subfolders, and search stops at about 275 results
description: A correspondence archive pull had to fall back to raw Graph calls, because list_mail_folders shows only top-level folders and search results are capped.
kind: feature
priority: medium
requested_by: claude-code
tags: [search, folders, archive]
created: 2026-09-22T02:53:48Z
---

Found while pulling a company's full 2026 correspondence with one vendor
out of two mailboxes on two tenants to file into git, 2026-09-22.

1. **`list_mail_folders` returns top-level folders only.** Mail filed in
   subfolders (e.g. an Archive tree) can't be reached through the tools.
2. **`list_messages` with `search` stops at about 275 results.** A
   mailbox with years of vendor mail needs date-windowed searches to see
   everything, and the tool gives no sign that it truncated.

The subagent worked around both with read-only Graph calls through the
ckm365 library (`childFolders`, and `$search` in date windows). That
worked, but it's the escape hatch the tools are meant to remove.

## Acceptance criteria

- [ ] `list_mail_folders` can recurse, or take a parent folder id
- [ ] Search paginates past Graph's per-page cap, or reports that it was truncated
- [ ] An archive pull of a vendor's mail across all folders needs no raw Graph

## Recurrence 2026-10-27 (claude-code, sec-toolchain)

Hit point 1 again. A DMARC-evidence task needed the aggregate reports that
sit in a subfolder of Inbox; `list_mail_folders` showed the Inbox had
child folders but not which, so there was no way to reach it through the
tools. Fell back to the `childFolders` escape hatch (graph-direct Recipe 2)
to resolve the subfolder id, then `g.paged`/`g.download` for the reports.
Reinforces the acceptance criterion "list_mail_folders can recurse, or
take a parent folder id" — a plain `folder` argument accepting a subfolder
path like `inbox/DMARC`, or a `parent` option on list_mail_folders, would
have avoided the raw Graph entirely.

Minor, same task: `messages/{id}/attachments` with
`$select=...,@odata.type` is rejected by Graph (that term isn't valid in
$select) — a small `list_attachments`-style helper that returns the
fileAttachment bytes path for a whole folder would help DMARC/report
pulls.
