"""Event-driven mail: Graph delta queries turned into wake-up primitives.

MCP has no server-initiated agent wake, so three read-tier shapes cover
"react to incoming mail" today:

- list_new_messages — one non-blocking delta poll; the caller owns the
  cadence and carries the delta_token between calls.
- wait_for_message — blocking long-poll inside a single tool call;
  simplest, but bounded by the MCP client's tool timeout.
- get_watch_command — the `ckm365 watch` background-process pattern: the
  process exits when mail matches, and the harness wakes the agent.

Graph delta facts baked in here: OUTLOOK message delta does NOT support
$deltatoken=latest (that is a directory-resource feature — live-tested:
Graph silently ignores it and starts enumerating the whole folder), so
the bootstrap instead filters the initial sync to
receivedDateTime ge (now - 60s); message delta supports $select but NOT
$filter-on-sender, $orderby, or $search, so sender/subject filters run
client-side; deleted or moved items arrive flagged "@removed" and are
skipped. The returned delta_token is the bare $deltatoken value from the
final @odata.deltaLink (it encodes the bootstrap's query options); we
rebuild the request URL ourselves so a caller-supplied token can never
point the bearer token off graph.microsoft.com. _drain caps pages so no
delta call can silently turn into a folder-sized crawl.
"""

import shlex
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from ..graph import GRAPH_BASE, Graph, GraphError
from ..graph import encode_segment as _seg, mailbox_path as _path
from ..models import MessageSummary
from .context import Ctx

# watch.py lives at <repo>/src/ckm365/tools/ — assumes a source checkout,
# which is how ckm365 runs (uv run --directory <repo>).
_REPO_ROOT = Path(__file__).resolve().parents[3]


_MAX_DELTA_PAGES = 50


def _drain(g: Graph, path: str, params: dict | None) -> tuple[list[dict], str]:
    """Follow a delta query through its @odata.nextLink pages; return the
    raw items plus the bare $deltatoken from the final @odata.deltaLink."""
    items: list[dict] = []
    url = path
    for _ in range(_MAX_DELTA_PAGES):
        page = g.get(url, params=params)
        params = None  # nextLink carries the full query string
        items += page.get("value", [])
        url = page.get("@odata.nextLink")
        if not url:
            break
        if not url.startswith(GRAPH_BASE):
            raise GraphError(0, "unsafe_next_link",
                             "refusing to follow @odata.nextLink off "
                             f"{GRAPH_BASE}: {url[:80]}")
    else:
        raise GraphError(0, "delta_pages_exceeded",
                         f"delta sync exceeded {_MAX_DELTA_PAGES} pages — "
                         "the token/bootstrap is not windowing correctly")
    link = page.get("@odata.deltaLink") or ""
    token = (parse_qs(urlparse(link).query).get("$deltatoken") or [""])[0]
    if not token:
        raise GraphError(0, "no_delta_token",
                         "delta response ended without a usable @odata.deltaLink")
    return items, token


def list_new_messages(ctx: Ctx, delta_token: str | None = None, *,
                      folder: str = "inbox",
                      from_addresses: list[str] | None = None,
                      subject_contains: str | None = None, top: int = 50,
                      account: str | None = None,
                      mailbox: str | None = None) -> dict:
    """One non-blocking "anything new?" poll via a Graph delta query.

    Without delta_token this BOOTSTRAPS: the sync window starts roughly
    now (mail from the last ~60s may already count — the buffer absorbs
    clock skew so nothing is missed). Feed each call's returned token into
    the next call to get only messages that arrived in between. Each
    watcher owns its own token, so independent agents can watch the same
    folder without interfering. from_addresses (case-insensitive sender
    match) and subject_contains (case-insensitive substring) filter
    client-side — Graph message delta cannot filter on sender. Returns
    {"messages": [matching summaries, capped at top], "delta_token": str,
    "matched": total matches (may exceed len(messages) when capped)}.
    """
    if not 1 <= top <= 500:
        raise ValueError("top must be between 1 and 500")
    g, mb = ctx.target(account, mailbox)
    path = _path(mb, f"mailFolders/{_seg(folder, 'folder')}/messages/delta")
    if delta_token:
        params = {"$deltatoken": delta_token}
    else:
        # Outlook delta has no 'latest' bootstrap: window the initial sync
        # by server-side receivedDateTime, 60s back to absorb clock skew.
        floor = (datetime.now(UTC) - timedelta(seconds=60)
                 ).strftime("%Y-%m-%dT%H:%M:%SZ")
        params = {"$select": MessageSummary.SELECT,
                  "$filter": f"receivedDateTime ge {floor}"}
    items, token = _drain(g, path, params)
    froms = {a.strip().lower() for a in from_addresses or []}
    needle = (subject_contains or "").lower()
    matches = []
    for item in items:
        if "@removed" in item:
            continue
        m = MessageSummary.from_graph(item)
        if froms and (m.sender.address if m.sender else "").lower() not in froms:
            continue
        if needle and needle not in (m.subject or "").lower():
            continue
        matches.append(m)
    return {"messages": matches[:top], "delta_token": token,
            "matched": len(matches)}


def wait_for_message(ctx: Ctx, *, timeout_s: float = 240, poll_s: float = 15,
                     delta_token: str | None = None, folder: str = "inbox",
                     from_addresses: list[str] | None = None,
                     subject_contains: str | None = None,
                     account: str | None = None,
                     mailbox: str | None = None) -> dict:
    """Block until a matching message arrives, or timeout_s elapses.

    Polls list_new_messages every poll_s seconds and returns the moment at
    least one message matches; on expiry returns "timed_out": True plus
    the latest delta_token so the caller can resume without a gap. With no
    delta_token, only mail arriving AFTER this call starts counts.

    WARNING: this holds the tool call open, and MCP clients enforce their
    own tool timeouts (Claude Code: MCP_TOOL_TIMEOUT) — keep timeout_s
    comfortably under the harness limit or the call is killed before the
    mail lands. For waits of many minutes or hours, call get_watch_command
    and run `ckm365 watch` as a background task instead: its exit wakes
    the agent with no tool call held open.
    """
    deadline = time.monotonic() + timeout_s
    token = delta_token
    while True:
        res = list_new_messages(ctx, token, folder=folder,
                                from_addresses=from_addresses,
                                subject_contains=subject_contains,
                                account=account, mailbox=mailbox)
        token = res["delta_token"]
        if res["matched"]:
            return {**res, "timed_out": False}
        if time.monotonic() >= deadline:
            return {**res, "timed_out": True}
        if poll_s > 0:
            time.sleep(poll_s)


def get_watch_command(ctx: Ctx, *, from_addresses: list[str] | None = None,
                      subject_contains: str | None = None,
                      timeout_s: float = 3600, folder: str = "inbox",
                      account: str | None = None,
                      mailbox: str | None = None) -> dict:
    """Build the exact shell command for the background-watch pattern.

    Run the returned command AS A BACKGROUND TASK (never wait on it in
    the foreground): it polls quietly and exits 0 the moment mail matching
    the baked-in filters arrives — the harness then wakes you, and you
    fetch the mail with list_new_messages or list_messages. Exit code 3
    means timeout_s passed with no match; 1 means error. Its output is
    counts and truncated ids only, never message content. Each run
    bootstraps its own delta token, so only mail arriving after launch
    (minus a ~60s clock-skew buffer) counts.
    """
    profile = ctx.profile(account)  # fail fast + bake an explicit account
    cmd = ["uv", "run", "--directory", str(_REPO_ROOT), "ckm365", "watch",
           "--account", profile.name, "--folder", folder,
           "--timeout", f"{timeout_s:g}"]
    if mailbox:
        cmd += ["--mailbox", mailbox]
    for a in from_addresses or []:
        cmd += ["--from", a]
    if subject_contains:
        cmd += ["--contains", subject_contains]
    return {
        "command": " ".join(shlex.quote(c) for c in cmd),
        "notes": ("Run this in the background. It exits 0 when matching "
                  "mail arrives (the harness wakes you — then fetch the "
                  f"mail), 3 after {timeout_s:g}s with no match, 1 on "
                  "error. Prints only counts and truncated message ids."),
    }
