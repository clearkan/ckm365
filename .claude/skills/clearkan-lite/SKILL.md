---
name: clearkan-lite
description: Do basic ClearKan board ops (create/move/update/close issues, file tickets from docs) without needing the full ClearKan harness installed.
---

# ClearKan Lite — Board ops without the harness

A ClearKan board is plain filesystem plus YAML, so any agent with file
tools can manage it when the full harness is unavailable.

Use neutral board vocabulary here: work-owner, work-coordinator,
work-doer, reviewer, approver, completion-handler, validation-check,
artifact, evidence, handoff, and escalation. Template-specific names
belong in the board's `TEAM.md` or template profile.

## Layout

```
<board-root>/
├── board.yaml
├── agents/
├── issues/
│   ├── backlog/
│   ├── todo/
│   ├── doing/
│   ├── blocked/
│   ├── done/
│   └── archived/
├── tasks/
├── workspaces/
└── events/
```

The directory a file lives in is the column. If the directory and YAML
disagree, the directory wins.

## Project key and issue IDs

Read `board.yaml` to find:
- `settings.project_key`
- `columns[]`

Issue IDs are scan-derived. To create a new issue:
1. scan existing issue IDs on the board
2. take the highest numeric suffix for the board's project key
3. use the next number

Do not rely on `settings.next_issue_number`; modern boards do not store
it.

## Filename convention

```
<project_key_lowercase>-<number>_<snake_case_slug>.yaml
```

Examples:
- `fin-21_reconcile_ap_batch.yaml`
- `ckn-42_update_board_guidance.yaml`

## Issue YAML schema

Common fields:

```yaml
id: XSG-21
title: Short description
column: backlog
status: backlog
created_at: '2026-04-06T12:00:00Z'
updated_at: '2026-04-06T12:00:00Z'
assignees:
- board-lead
description: |-
  Multi-line markdown description.
dependencies: []
parent_id: null
priority: medium
issue_type: task
tags: []
requested_by: board-lead
due_date: null
history:
- at: '2026-04-06T12:00:00Z'
  by: board-lead
  details: Issue created in column backlog
  event: created
version: 1
```

## Common operations

### 1. Create an issue

1. Read `board.yaml` and determine the `project_key`.
2. Scan existing issues and compute the next numeric suffix.
3. Pick the target column.
4. Write the YAML file at:
   `<board-root>/issues/<column>/<key_lower>-<num>_<slug>.yaml`
5. Append to `board_activity.log` if the board uses one.

### 2. Move an issue

1. Move the file into the destination column directory.
2. Update `column`, `status`, and `updated_at`.
3. Append a history entry describing the move.

### 3. Update an issue

1. Edit the needed fields.
2. Update `updated_at`.
3. Append a history entry.

### 4. Close an issue

Move it to `done/` using the same rules as any other column move.

## What not to do

- Do not finalize, discard, or overwrite another agent's artifacts
  unless the requester explicitly asks
- Do not delete issues; archive them
- Do not skip `updated_at`
- Do not skip `history`
- Do not invent new columns
- Do not reuse IDs

## Sanity checks

- every new file's `column` matches its directory
- every new file's `id` matches its filename prefix
- the new numeric suffix is higher than every existing issue for the board key
- there are no duplicate IDs
- `updated_at` was changed on every modified issue

## Reference files

- `references/board_yaml_example.yaml`
- `references/issue_template.yaml`
