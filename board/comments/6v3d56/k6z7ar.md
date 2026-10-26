---
type: comment
at: "2026-10-26T13:02:09Z"
by: "claude"
event: "commented"
---

Re-run on v2.10.1 against the folder that found the bug: confirmed fixed.

Fresh branch in the same throwaway worktree, from the same base commit as
the v2.10.0 run, so both runs started from identical files. Dry run, apply,
then apply again, with the same profile as before.

| Step | v2.10.1 | v2.10.0 |
|---|---|---|
| upgrade | 18 applied, dry run "body kept" x18 | 18 applied |
| pair applied | 22 | 22 |
| pair failed, note owns `<stem>.md` | 25 | 25 |
| manual, skipped | 60 | 60 |
| second apply | nothing new | nothing new |

Checked byte for byte against the base commit:

- **All 18 bodies are byte-identical**: every byte after the closing fence.
- **The six annotated records keep every section.** Their `## ` heading
  counts before and after are 5/5, 6/6, 5/5, 9/9, 6/6 and 7/7. Under
  v2.10.0 those six lost 34 sections.
- **All 18 front matters change exactly as specified.** `timestamp` and
  `exported_by` are removed and one `generated: {by: "ckm365/2.10.1", at:
  <old timestamp>}` line is added. Every other line is unchanged and in its
  original order.
- **The twelve clean records match the v2.10.0 output** except for the
  version inside `generated` (2.10.0 vs 2.10.1): one line, nothing else.
- **The 22 new pair records match the v2.10.0 output** except for the same
  version stamp.
- No `.part` files left behind.

The v2.10.1 result is committed on the throwaway branch, which stays local
and unpushed. The still-open items are unchanged: a pair destination for the
25 taken names, and a `note` kind for the front-matter-less bucket (r2wgna).
