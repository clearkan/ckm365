---
type: "issue"
title: "Bulk correspondence export — thread, folder or id list to a project folder"
created: "2026-09-21T00:00:00Z"
resource: "oif:ckm/k4r9tw"
aliases: ["CKM-53"]
kind: "feature"
priority: "medium"
requested_by: "human:seanwy"
tags: ["mail", "export"]
---

`export_message` exports one message at a time. Past sessions kept
hand-rolling a wrapper around it: take a list of ids, then run
export_message and the attachment downloads for each into a project's
correspondence folder. That wrapper is a recurring throwaway script in
tmp/.

Proposal: a read-tier tool, or a thin skill over the existing tools. It
takes a selector (explicit ids, a conversation id, or a folder plus a date
or sender filter) and a destination directory, and writes one export per
message plus its attachments. It skips what is already there, so a rerun
into a git repo is idempotent. Decide between tool and skill when this is
picked up: a tool only if the fan-out needs Graph batching; otherwise a
skill over the existing tools is lighter.
