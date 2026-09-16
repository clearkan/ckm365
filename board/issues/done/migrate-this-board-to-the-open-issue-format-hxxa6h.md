---
type: "issue"
title: "Migrate this board to the Open Issue Format"
created: "2026-09-16T09:30:00Z"
resource: "oif:ckm/hxxa6h"
aliases: ["CKM-50"]
kind: "task"
priority: "medium"
requested_by: "human:seanwy"
tags: ["board", "oif", "migration"]
---

This board is clearkan-lite: YAML issues, directory as
column, `ckm-NN_slug.yaml`. The Open Issue Format was extracted from exactly
that shape and published at https://oif.md, so the migration is small and the
format is now specified and validated rather than implied by a tool.

What changes:

- One Markdown file per issue with YAML frontmatter, named `<slug>-<id>.md`
  where the id is six random Crockford base32 characters. `CKM-49` survives in
  `aliases`, so every existing reference in the code, docs and commit messages
  keeps resolving.
- The `status` and `column` fields are deleted. The directory already carries
  the state and holding it twice lets them disagree.
- The inline `history` list becomes one comment file per entry under
  `comments/<issue-id>/`. The mapping is exact: an entry's `at`, `by` and text
  are a comment's three required keys, and `event` rides along as an extra key
  because consumers preserve keys they do not recognise.
- `description` becomes the body, so an issue reads as a document.
- Everything else, including tags, priority and parent, carries across
  unchanged.

Why it is worth doing here specifically: the correspondence work in CKM-49
points a board at an evidence corpus using `about` entries carrying
`mid:` resources. That mechanism is defined by OIF and has no equivalent in
clearkan-lite, so this board cannot cite the messages it exports until it
moves.

`pip install oifmd` then `oifmd validate board` checks the result against the
specification. Section 7.3 of the spec covers the migration and gives the
mapping table; the agent skill at https://oif.md/skill.md is enough for an
agent to do the conversion without further instruction.

Derive each new id deterministically from the existing key if the migration
might be run more than once, or a second run produces a second set of files.

Not urgent. The board works. This is about being able to link to
correspondence, and about dogfooding a format we publish.
