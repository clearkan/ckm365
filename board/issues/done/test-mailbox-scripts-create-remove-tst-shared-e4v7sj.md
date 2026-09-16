---
type: "issue"
title: "Test mailbox scripts — create/remove tst.* shared mailboxes (interactive first run)"
created: "2026-07-29T21:47:41Z"
resource: "oif:ckm/e4v7sj"
aliases: ["CKM-9"]
kind: "task"
priority: "medium"
assignees: ["claude"]
requested_by: "human:seanwy"
tags: ["testing", "interactive"]
---

scripts/create-test-mailbox.ps1 + scripts/remove-test-mailbox.ps1 using
ExchangeOnlineManagement (New-Mailbox -Shared) — pattern
tst.<suffix>@tenant-a.example, no license cost. az/Graph only for Entra-side.
Test mailboxes must fall inside the RBAC management scope (or scope filter
matches tst.*). First run together interactively.

Later (not yet): pytest integration suite that provisions a mailbox,
exercises createReply -> PATCH -> verify-draft, tears down. Structure
tooling now so that is possible; no CI harness yet.
