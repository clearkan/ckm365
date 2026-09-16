---
type: board
oif: "0.1"
key: ckm
title: "ckm365 M365 Graph MCP Server"
columns:
  - name: backlog
  - name: todo
    wip: 10
  - name: doing
    wip: 5
  - name: blocked
    wip: 5
  - name: done
    complete: true
  - name: archived
    complete: true
    hidden: true
kinds:
  - name: epic
    contains: [task, feature, improvement, bug]
  - name: task
    contains: [task, feature, improvement, bug]
  - name: bug
  - name: feature
  - name: improvement
---

Task board for ckm365, a minimal multi-tenant Microsoft Graph MCP server
for mail and calendar.

Migrated from clearkan-lite on 2026-09-16 (CKM-50). Issue ids are DERIVED
from the old `CKM-NN` keys rather than random, so the migration is
idempotent: running it again reproduces these files instead of a second
board. Every issue keeps its old key in `aliases`, because `CKM-NN` is
referenced throughout the code, docs, CHANGELOG and commit history.

Status lives in the directory and nowhere else. The old `column`/`status`
fields are gone, as is `updated_at` — the newest comment carries that.
