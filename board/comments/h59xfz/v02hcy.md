---
type: comment
at: "2026-10-26T10:05:00Z"
by: "claude"
event: "completed"
---

Squash-merged to main by Claude after review: the diff is the three
renames and their uses, nothing else. Offline suite 189 passed, 15
skipped, on main.

What the proving run established about the loop on this box:

- Codex stopped on the first blocker and reported it instead of working
  around it, which is the behaviour the preamble asks for.
- The blocker was the environment: inside the workspace-write sandbox the
  home directory is read-only, so uv cannot use its cache under it, and
  two tests wrote to the real state directory. Fixes: run the dispatcher
  with UV_CACHE_DIR pointing at a pre-warmed cache under /tmp (43 MB for
  this repo; /tmp stays writable in that sandbox), and a conftest that
  points XDG_STATE_HOME at a temp dir. Both reproduced and verified with
  `codex sandbox` without a model call.
- tmp/ is git-ignored, so a card's gate command must mkdir it.
- Round 2 cost 7 model calls, peak context 25k, no polling.
