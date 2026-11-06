---
type: "issue"
title: "search_messages past Graph's 275-row cap, and list_mail_folders into subfolders"
created: "2026-11-06T02:00:00Z"
resource: "oif:ckm/z2k7hm"
kind: "task"
priority: "medium"
requested_by: "human:seanwy"
assignees: ["codex"]
tags: ["mail", "search", "folders", "copilot-card"]
---

Implements xfccc0 (`board/issues/backlog/list-subfolders-and-uncapped-search-for-archive-pulls-xfccc0.md`).
Two spec files on main, each skipped as a module until its feature exists:
`tests/test_mail_search.py` (search) and `tests/test_mail_folders.py`
(folders). Read both in full first; their module docstrings carry the
live measurements this design rests on.

## Deliverable 1: search_messages

In `src/ckm365/tools/mail/read.py`, add

    def search_messages(ctx: Ctx, query: str, *, since: str, until: str | None = None,
                        folder: str | None = None, max_results: int = 1000,
                        account: str | None = None,
                        mailbox: str | None = None) -> SearchResult

and in `src/ckm365/models.py` a new dataclass, placed after `MessageSummary`:

    @dataclass
    class SearchResult:
        messages: list[MessageSummary] = field(default_factory=list)
        windows: int = 0                  # Graph searches run
        truncated_days: list[str] = field(default_factory=list)  # ISO dates, ascending
        hit_max_results: bool = False

Behaviour:
- Validate before any request: `query.strip()` non-empty; `since` and
  `until` are ISO dates (`date.fromisoformat`), `until` defaults to
  today in UTC, `until >= since`; `1 <= max_results <= 5000`; `folder`
  through `_seg` when given. ValueError otherwise.
- One window = one Graph search, all pages: GET `<mailbox>/messages`
  (or `<mailbox>/mailFolders/<folder>/messages`) with `$search` exactly
  `"(<escaped query>) AND received:<a>..<b>"` (escape `\` then `"`
  exactly as `list_messages` does), `$select=MessageSummary.SELECT`,
  `$top=100`, and NO `$orderby`/`$filter`. Follow nextLinks with
  `g.paged(..., max_items=SEARCH_CAP + 1)` or equivalent.
- `SEARCH_CAP = 275`, a module constant with a comment saying it was
  measured on two tenants on 2026-11-06. A window that returns
  `>= SEARCH_CAP` rows is full: if it spans more than one day, split it
  at the midpoint day into `[a, mid]` and `[mid+1, b]` and search both
  (discard the full window's rows); if it is a single day, keep its rows
  and record the day in `truncated_days`.
- Process windows NEWEST FIRST (a stack where the newer half is searched
  first). Stop when the collected count reaches `max_results`; then set
  `hit_max_results=True`. Return messages deduplicated by id, sorted by
  `received` descending, trimmed to `max_results`.
- `windows` counts the Graph searches run (a window and its pages count
  once).
- Docstring (the MCP description, 15-25 lines, same voice as
  `list_messages`): the 275 cap and that it is silent; what windows and
  truncated_days mean; KQL query syntax works inside `query`; when to
  prefer list_messages (recent mail, filters).
- In `list_messages`'s docstring, add one bullet: `search` stops at 275
  rows SILENTLY (Graph's cap); use search_messages for anything that can
  have more.
- Register: `tools/mail/__init__.py` (import, `__all__`, and add
  `search_messages` to the `read.py` line of the module docstring) and
  `READ["mail"]` in `src/ckm365/tools/__init__.py`, right after
  `list_messages`. Export `SearchResult` from `ckm365.models` (it is
  imported by name from there).

## Deliverable 2: list_mail_folders

    def list_mail_folders(ctx: Ctx, *, parent: str | None = None,
                          recursive: bool = False, account: str | None = None,
                          mailbox: str | None = None) -> list[MailFolder]

- `MailFolder` gains `parent_id: str = ""` and `path: str = ""` (append
  after `child_folders`, defaults so the API stays compatible) and
  `parentFolderId` in its `SELECT`. `from_graph` fills `parent_id`; set
  `path = name` there, and the walk overwrites it.
- `parent` given: GET `<mailbox>/mailFolders/<_seg(parent)>/childFolders`;
  otherwise `<mailbox>/mailFolders` as today. Same params as today.
- `recursive=True`: depth-first pre-order from that starting list; for
  each folder with `child_folders > 0`, GET its `childFolders` and
  insert those children (in Graph's order) right after it, each with
  `path = parent.path + "/" + child.name`. Never request children of a
  folder whose `child_folders` is 0.
- Docstring: one short paragraph saying what parent/recursive do and
  that `path` is relative to the starting point.

## Preset counts

One new read tool moves SIX numbers in
`tests/test_offline.py::test_tools_for_presets`, each up by one: lines
254, 255, 256 (`mail` read/write/send: 15, 30, 31) and lines 283, 284,
287 (`all` write, `all` send, `all`+`teams`: 35, 36, 39). Those six
numbers are the only edits allowed in that file.

## Files you may touch

- `src/ckm365/tools/mail/read.py`, `src/ckm365/models.py`
- `src/ckm365/tools/mail/__init__.py`, `src/ckm365/tools/__init__.py`
- `tests/test_offline.py`: the six numbers above.

Read only those plus the two spec files, `src/ckm365/graph.py` lines
39-75 and 271-295 (`encode_segment`, `mailbox_path`, `paged`) and
`src/ckm365/tools/context.py` lines 130-145 (`pull`). Do not edit the
spec files: if a test looks wrong, say so in open_questions and make the
rest pass.

## Gate

    mkdir -p tmp; uv run --offline pytest tests/ -q > tmp/pytest.log 2>&1; echo EXIT=$?; tail -5 tmp/pytest.log

Before: `251 passed, 17 skipped`. Expected after: all passing, `15
skipped`, about 28 more passed (the two spec modules un-skip; one test
is parametrized 7 ways). Report the counted result.

## Not in scope

- Changing `list_messages`' behaviour or return type (docstring bullet only).
- Any live check, `CKM365_LIVE_*`, anything under `~/.config/ckm365`.
- Version bump, CHANGELOG, README, docs, board files. No commits.

## Relates to

- xfccc0 (backlog): the issue. k4r9tw (bulk export) builds on both.
