"""Offline spec for search_messages (xfccc0): a search that does not stop
at Graph's silent cap.

Measured 2026-11-06 on two tenants: Graph's `$search` on messages returns
AT MOST 275 rows. The nextLink chain simply ends; nothing says the result
was cut. `list_messages(search=...)` inherits that, so an archive pull of
years of vendor mail saw 275 and had to fall back to raw Graph.

What does work (same measurement): a KQL date range inside the search
string, `received:YYYY-MM-DD..YYYY-MM-DD` (inclusive, day granularity),
narrows the result, and each narrower query gets its own 275. The user's
query MUST be parenthesised: `meeting OR invoice AND received:...` let
the OR swallow the range (275 rows from the wrong years), while
`(meeting OR invoice) AND received:...` returned the right 176.

So search_messages bisects: run the query over [since, until]; when a
window comes back with 275 rows, split it in half by date and run both
halves; a single day that still returns 275 is reported as truncated
rather than silently cut. Windows are processed newest first, so when
max_results stops the walk the result holds the newest matches.

The fake Graph below enforces exactly that contract: it parses the
`$search` value, refuses anything not shaped `"(<query>) AND
received:A..B"`, returns that range's messages newest first, caps at
275, and pages by $top with nextLinks.
"""

import re
from datetime import date, timedelta
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from ckm365.tools import mail

if not hasattr(mail, "search_messages"):
    pytest.skip("search_messages not built yet (xfccc0)", allow_module_level=True)

from ckm365.config import Profile  # noqa: E402
from ckm365.graph import GRAPH_BASE, Graph  # noqa: E402
from ckm365.models import MessageSummary, SearchResult  # noqa: E402
from ckm365.tools import Ctx  # noqa: E402

MAILBOX = "operator@tenant-a.example"
CAP = 275
SEARCH_RE = re.compile(r'^"\((.*)\) AND received:(\d{4}-\d{2}-\d{2})\.\.(\d{4}-\d{2}-\d{2})"$')


class FakeAuth:
    def token(self):
        return "fake-token"

    def username(self):
        return MAILBOX


def corpus(per_day: dict[str, int]) -> list[dict]:
    """Messages keyed by day: {'2026-01-05': 3} makes three that day."""
    rows = []
    for day, n in per_day.items():
        for i in range(n):
            rows.append({"id": f"m-{day}-{i:04d}",
                         "receivedDateTime": f"{day}T{(i % 24):02d}:{(i // 24) % 60:02d}:00Z",
                         "subject": f"s {day} {i}",
                         "from": {"emailAddress": {"address": "other-user@tenant-b.example"}},
                         "isRead": True, "hasAttachments": False})
    return rows


def _ctx(rows, *, cap=CAP):
    seen = []

    def handler(request):
        seen.append(request)
        q = {k: v[0] for k, v in parse_qs(urlsplit(str(request.url)).query).items()}
        m = SEARCH_RE.match(q.get("$search", ""))
        if not m:
            return httpx.Response(400, json={"error": {"code": "BadRequest",
                                                       "message": "unexpected $search"}})
        a, b = m.group(2), m.group(3)
        hits = sorted((r for r in rows if a <= r["receivedDateTime"][:10] <= b),
                      key=lambda r: r["receivedDateTime"], reverse=True)[:cap]
        top, skip = int(q.get("$top", "10")), int(q.get("$skiptoken", "0"))
        page = {"value": hits[skip:skip + top]}
        if skip + top < len(hits):
            nxt = dict(q, **{"$skiptoken": str(skip + top)})
            page["@odata.nextLink"] = str(httpx.URL(
                GRAPH_BASE + request.url.path.removeprefix("/v1.0"), params=nxt))
        return httpx.Response(200, json=page)

    ctx = Ctx(profiles={"tenant-a": Profile(
        name="tenant-a", tenant_id="t1", client_id="c1", default_mailbox=MAILBOX)})
    ctx.set_graph("tenant-a", Graph(FakeAuth(), transport=httpx.MockTransport(handler)))
    return ctx, seen


def days(start: str, n: int, per: int) -> dict[str, int]:
    d0 = date.fromisoformat(start)
    return {(d0 + timedelta(days=i)).isoformat(): per for i in range(n)}


def search(ctx, **kw):
    kw.setdefault("query", "invoice")
    return mail.search_messages(ctx, **kw)


# --- the result -------------------------------------------------------------

def test_under_the_cap_is_one_window_and_complete(tmp_path):
    ctx, seen = _ctx(corpus(days("2026-01-01", 10, 5)))           # 50 rows
    r = search(ctx, since="2026-01-01", until="2026-01-31")
    assert isinstance(r, SearchResult)
    assert len(r.messages) == 50
    assert all(isinstance(m, MessageSummary) for m in r.messages)
    assert r.windows == 1
    assert r.truncated_days == [] and r.hit_max_results is False
    q = parse_qs(urlsplit(str(seen[0].url)).query)["$search"][0]
    assert q == '"(invoice) AND received:2026-01-01..2026-01-31"'


def test_results_are_newest_first_and_unique():
    ctx, _ = _ctx(corpus(days("2026-01-01", 10, 5)))
    r = search(ctx, since="2026-01-01", until="2026-01-31")
    stamps = [m.received for m in r.messages]
    assert stamps == sorted(stamps, reverse=True)
    assert len({m.id for m in r.messages}) == len(r.messages)


def test_over_the_cap_bisects_until_every_window_is_complete():
    rows = corpus(days("2026-01-01", 100, 10))                     # 1000 rows
    ctx, _ = _ctx(rows)
    r = search(ctx, since="2026-01-01", until="2026-04-30", max_results=5000)
    assert len(r.messages) == 1000
    assert {m.id for m in r.messages} == {x["id"] for x in rows}
    assert r.windows > 1
    assert r.truncated_days == [] and r.hit_max_results is False


def test_a_single_day_over_the_cap_is_reported_not_hidden():
    per_day = days("2026-03-01", 5, 3)
    per_day["2026-03-03"] = 400                                     # one heavy day
    ctx, _ = _ctx(corpus(per_day))
    r = search(ctx, since="2026-03-01", until="2026-03-05")
    assert r.truncated_days == ["2026-03-03"]
    on_day = [m for m in r.messages if m.received.startswith("2026-03-03")]
    assert len(on_day) == CAP                                       # what Graph gave
    assert len(r.messages) == CAP + 4 * 3                           # the rest complete


def test_max_results_keeps_the_newest_and_says_so():
    rows = corpus(days("2026-01-01", 100, 10))
    ctx, _ = _ctx(rows)
    r = search(ctx, since="2026-01-01", until="2026-04-30", max_results=300)
    assert len(r.messages) == 300 and r.hit_max_results is True
    newest = sorted(rows, key=lambda x: x["receivedDateTime"], reverse=True)[:300]
    assert [m.id for m in r.messages] == [x["id"] for x in newest]


def test_an_empty_range_is_one_window_and_empty():
    ctx, _ = _ctx([])
    r = search(ctx, since="2026-01-01", until="2026-12-31")
    assert r.messages == [] and r.windows == 1 and r.truncated_days == []


# --- the query --------------------------------------------------------------

def test_the_whole_mailbox_is_searched_by_default():
    ctx, seen = _ctx(corpus(days("2026-01-01", 2, 1)))
    search(ctx, since="2026-01-01", until="2026-01-02")
    assert seen[0].url.path == f"/v1.0/users/{MAILBOX}/messages"


def test_folder_scopes_the_search():
    ctx, seen = _ctx(corpus(days("2026-01-01", 2, 1)))
    search(ctx, since="2026-01-01", until="2026-01-02", folder="archive")
    assert seen[0].url.path == f"/v1.0/users/{MAILBOX}/mailFolders/archive/messages"


def test_quotes_and_backslashes_in_the_query_are_escaped():
    ctx, seen = _ctx([])
    search(ctx, query='subject:"Q1 figures" path\\x', since="2026-01-01",
           until="2026-01-02")
    q = parse_qs(urlsplit(str(seen[0].url)).query)["$search"][0]
    assert q == '"(subject:\\"Q1 figures\\" path\\\\x) AND received:2026-01-01..2026-01-02"'


def test_select_is_the_summary_projection():
    ctx, seen = _ctx(corpus(days("2026-01-01", 1, 1)))
    search(ctx, since="2026-01-01", until="2026-01-01")
    q = parse_qs(urlsplit(str(seen[0].url)).query)
    assert q["$select"][0] == MessageSummary.SELECT
    assert "$orderby" not in q and "$filter" not in q    # Graph rejects both with $search


# --- validation -------------------------------------------------------------

@pytest.mark.parametrize("kw", [
    {"query": ""}, {"query": "   "},
    {"since": "yesterday"}, {"since": "2026-02-30"},
    {"until": "2025-12-31"},                                 # before since
    {"max_results": 0}, {"max_results": 5001},
])
def test_bad_arguments_raise_before_any_request(kw):
    ctx, seen = _ctx([])
    args = dict(query="invoice", since="2026-01-01", until="2026-01-31")
    args.update(kw)
    with pytest.raises(ValueError):
        mail.search_messages(ctx, **args)
    assert not seen


def test_registered_as_a_read_tier_mail_tool():
    from ckm365 import tools
    assert mail.search_messages in tools.READ["mail"]
    assert mail.search_messages not in tools.WRITE["mail"]


def test_list_messages_warns_about_the_cap():
    doc = mail.list_messages.__doc__
    assert "275" in doc and "search_messages" in doc
