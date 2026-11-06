"""Offline spec for export_messages, bulk correspondence export (k4r9tw,
CKM-53).

Past sessions kept hand-rolling the same wrapper: take some messages,
export each into a project's correspondence folder, fetch the
attachments. This is that wrapper, as a read-tier tool (a tool rather
than a skill so every MCP client, Codex included, gets it).

- ONE selector: `message_ids`, `conversation_id` (every message of a
  thread, across folders: `$filter=conversationId eq '...'` on
  /messages, measured to work live; Graph refuses $orderby with it, so
  sort locally), or `folder` with optional `since` / `from_address`
  (list_messages' own predicates).
- Messages are exported OLDEST FIRST into `dest_dir`, each under the
  convention proposed in 4qn81m and deferred to here:
  `YYYYMMDD_<slug>_<token>.md`, where the date is the received date
  (UTC), the slug is the subject without reply/forward prefixes,
  lower-cased, runs of anything outside a-z0-9 collapsed to "-", at most
  50 characters, trimmed of "-" ("no-subject" when empty), and the token
  is the first 8 hex characters of SHA-1 of the Message-ID without angle
  brackets. Stable: the same message gets the same name on every run
  and in every mailbox.
- Idempotent: each export runs with `dedupe_dir=dest_dir`, so a message
  already filed under ANY name (a hand-written one too) is reported
  `already`, never written twice.
- `eml=True` also writes `<stem>.eml`; `attachments=True` saves each
  non-inline attachment into the directory `<stem>/` (an existing file
  there is kept, not overwritten).
- `dry_run=True` lists, names and dedupes, writes nothing.
- `max_messages` bounds the run; a selector with more says `truncated`.

Skipped as a module until mail.export_messages exists.
"""

import hashlib
import json
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from ckm365.tools import mail

if not hasattr(mail, "export_messages"):
    pytest.skip("export_messages not built yet (k4r9tw)", allow_module_level=True)

from ckm365.config import Profile  # noqa: E402
from ckm365.graph import Graph  # noqa: E402
from ckm365.tools import Ctx  # noqa: E402
from ckm365.tools.mail import bulk  # noqa: E402

MAILBOX = "operator@tenant-a.example"
CONV = "AAQkADconv" + "c" * 70


class FakeAuth:
    def token(self):
        return "fake-token"

    def username(self):
        return MAILBOX


def msg(mid, subject, received, *, imid=None, conv=CONV, folder="INBOX",
        attachments=()):
    return {"id": mid, "subject": subject, "receivedDateTime": received,
            "from": {"emailAddress": {"address": "other-user@tenant-b.example"}},
            "toRecipients": [{"emailAddress": {"address": MAILBOX}}],
            "body": {"contentType": "text", "content": f"Body of {mid}."},
            "uniqueBody": {"contentType": "text", "content": f"New in {mid}."},
            "bodyPreview": f"Body of {mid}.",
            "internetMessageId": imid if imid is not None else f"<{mid}@tenant-b.example>",
            "conversationId": conv, "parentFolderId": folder,
            "webLink": f"https://outlook.example/{mid}",
            "hasAttachments": bool(attachments), "isRead": True, "isDraft": False,
            "_attachments": list(attachments)}


THREAD = [
    msg("m3", "RE: Q1 figures", "2026-03-04T08:00:00Z"),
    msg("m1", "Q1 figures", "2026-03-01T09:30:00Z",
        attachments=[{"@odata.type": "#microsoft.graph.fileAttachment", "id": "a1",
                      "name": "q1.xlsx", "contentType": "x", "size": 10,
                      "isInline": False},
                     {"@odata.type": "#microsoft.graph.fileAttachment", "id": "a2",
                      "name": "logo.png", "contentType": "image/png", "size": 5,
                      "isInline": True}]),
    msg("m2", "Re: Q1 figures", "2026-03-02T10:00:00Z", folder="SENT"),
    msg("m9", "Unrelated", "2026-03-03T00:00:00Z", conv="OTHER"),
]


def _ctx(messages=THREAD):
    seen = []
    by_id = {m["id"]: m for m in messages}

    def strip(m):
        return {k: v for k, v in m.items() if not k.startswith("_")}

    def handler(request):
        seen.append(request)
        p = request.url.path.removeprefix(f"/v1.0/users/{MAILBOX}/")
        q = {k: v[0] for k, v in parse_qs(urlsplit(str(request.url)).query).items()}
        if p == "mailFolders/sentitems":
            return httpx.Response(200, json={"id": "SENT"})
        if p == "messages" and "conversationId eq" in q.get("$filter", ""):
            cid = q["$filter"].split("'")[1].replace("''", "'")
            return httpx.Response(200, json={"value": [
                strip(m) for m in messages if m["conversationId"] == cid]})
        if p.startswith("mailFolders/") and p.endswith("/messages"):
            return httpx.Response(200, json={"value": [strip(m) for m in messages]})
        parts = p.split("/")
        if parts[0] == "messages" and len(parts) >= 2 and parts[1] in by_id:
            m = by_id[parts[1]]
            if parts[-1] == "$value":
                return httpx.Response(200, content=(
                    f"Message-ID: {m['internetMessageId']}\r\nSubject: x\r\n\r\nraw\r\n").encode())
            if parts[-1] == "attachments":
                return httpx.Response(200, json={"value": m["_attachments"]})
            return httpx.Response(200, json=strip(m))
        return httpx.Response(404, json={"error": {"code": "NotFound", "message": p}})

    ctx = Ctx(profiles={"tenant-a": Profile(
        name="tenant-a", tenant_id="t1", client_id="c1", default_mailbox=MAILBOX)})
    ctx.set_graph("tenant-a", Graph(FakeAuth(), transport=httpx.MockTransport(handler)))
    return ctx, seen


def token(imid):
    return hashlib.sha1(imid.strip("<>").encode()).hexdigest()[:8]


def by_id(result):
    return {r["message_id"]: r for r in result["results"]}


@pytest.fixture
def downloads(monkeypatch):
    calls = []

    def fake(ctx, message_id, dest_path, *, attachment_id=None, name=None,
             account=None, mailbox=None):
        calls.append((message_id, dest_path, attachment_id))
        return {"path": dest_path, "bytes": 10}

    monkeypatch.setattr(bulk, "download_attachment", fake)
    return calls


# --- naming -----------------------------------------------------------------

@pytest.mark.parametrize("subject,slug", [
    ("Q1 figures", "q1-figures"),
    ("RE: Fwd: AW: Q1 figures!!", "q1-figures"),
    ("  ", "no-subject"),
    (None, "no-subject"),
    ("Ünïcode & ümlauts / 2026", "n-code-mlauts-2026"),
    ("x" * 80, "x" * 50),
])
def test_file_stem_convention(subject, slug):
    imid = "<abc123@tenant-b.example>"
    assert bulk.file_stem(subject, "2026-03-01T23:59:00Z", imid) == \
        f"20260301_{slug}_{token(imid)}"


def test_the_token_ignores_angle_brackets():
    a = bulk.file_stem("s", "2026-03-01T00:00:00Z", "<x@y.example>")
    b = bulk.file_stem("s", "2026-03-01T00:00:00Z", "x@y.example")
    assert a == b


# --- selectors --------------------------------------------------------------

def test_a_conversation_exports_every_message_oldest_first(tmp_path):
    ctx, seen = _ctx()
    r = mail.export_messages(ctx, str(tmp_path), conversation_id=CONV)
    assert [x["message_id"] for x in r["results"]] == ["m1", "m2", "m3"]
    assert all(x["outcome"] == "written" for x in r["results"])
    names = sorted(p.name for p in tmp_path.iterdir())
    assert names == sorted(f"{x['name']}" for x in r["results"])
    assert by_id(r)["m1"]["name"] == f"20260301_q1-figures_{token('<m1@tenant-b.example>')}.md"
    f = next(q for q in seen if "$filter" in q.url.params)
    assert f.url.path == f"/v1.0/users/{MAILBOX}/messages"       # across folders
    assert "$orderby" not in f.url.params                         # Graph refuses it


def test_records_are_real_exports(tmp_path):
    ctx, _ = _ctx()
    r = mail.export_messages(ctx, str(tmp_path), message_ids=["m1"])
    text = (tmp_path / r["results"][0]["name"]).read_text()
    assert 'internet_message_id: "<m1@tenant-b.example>"' in text


def test_message_ids_keep_the_oldest_first_order_too(tmp_path):
    ctx, _ = _ctx()
    r = mail.export_messages(ctx, str(tmp_path), message_ids=["m3", "m1"])
    assert [x["message_id"] for x in r["results"]] == ["m1", "m3"]


def test_a_folder_selector_uses_the_list_predicates(tmp_path):
    ctx, seen = _ctx()
    mail.export_messages(ctx, str(tmp_path), folder="archive", since="2026-03-01",
                         from_address="other-user@tenant-b.example", dry_run=True)
    q = next(x for x in seen if x.url.path.endswith("/mailFolders/archive/messages"))
    f = parse_qs(urlsplit(str(q.url)).query)["$filter"][0]
    assert "receivedDateTime ge 2026-03-01" in f and "other-user@tenant-b.example" in f


@pytest.mark.parametrize("kw", [
    {}, {"message_ids": ["m1"], "conversation_id": CONV},
    {"conversation_id": CONV, "folder": "inbox"},
    {"message_ids": []}, {"message_ids": ["m1"], "since": "2026-01-01"},
    {"conversation_id": CONV, "max_messages": 0},
    {"conversation_id": CONV, "max_messages": 1001},
])
def test_exactly_one_selector_and_sane_bounds(tmp_path, kw):
    ctx, seen = _ctx()
    with pytest.raises(ValueError):
        mail.export_messages(ctx, str(tmp_path), **kw)
    assert not seen


# --- idempotence and safety -------------------------------------------------

def test_a_second_run_writes_nothing(tmp_path):
    ctx, _ = _ctx()
    mail.export_messages(ctx, str(tmp_path), conversation_id=CONV)
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    r = mail.export_messages(ctx, str(tmp_path), conversation_id=CONV)
    assert [x["outcome"] for x in r["results"]] == ["already"] * 3
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == before
    assert r["counts"] == {"already": 3}


def test_a_message_filed_under_a_hand_written_name_is_already(tmp_path):
    (tmp_path / "my-notes.md").write_text(
        '---\nsubject: Q1\ninternet_message_id: "<m1@tenant-b.example>"\n---\nmine\n')
    ctx, _ = _ctx()
    r = mail.export_messages(ctx, str(tmp_path), message_ids=["m1"])
    assert r["results"][0]["outcome"] == "already"
    assert "my-notes.md" in r["results"][0]["detail"]


def test_dry_run_names_and_dedupes_but_writes_nothing(tmp_path):
    ctx, _ = _ctx()
    r = mail.export_messages(ctx, str(tmp_path), conversation_id=CONV, dry_run=True)
    assert [x["outcome"] for x in r["results"]] == ["would-write"] * 3
    assert all(x["name"].endswith(".md") for x in r["results"])
    assert list(tmp_path.iterdir()) == []
    assert r["dry_run"] is True


def test_one_failure_does_not_stop_the_rest(tmp_path):
    ctx, _ = _ctx()
    r = mail.export_messages(ctx, str(tmp_path), message_ids=["m1", "nope", "m2"])
    assert by_id(r)["nope"]["outcome"] == "failed"
    assert by_id(r)["m1"]["outcome"] == by_id(r)["m2"]["outcome"] == "written"


def test_max_messages_truncates_and_says_so(tmp_path):
    ctx, _ = _ctx()
    r = mail.export_messages(ctx, str(tmp_path), conversation_id=CONV, max_messages=2)
    assert [x["message_id"] for x in r["results"]] == ["m1", "m2"]
    assert r["truncated"] is True
    r = mail.export_messages(ctx, str(tmp_path), conversation_id=CONV, max_messages=3)
    assert r["truncated"] is False


def test_dest_dir_is_fenced(tmp_path, monkeypatch):
    monkeypatch.setenv("CKM365_DOWNLOAD_ROOT", str(tmp_path / "root"))
    (tmp_path / "root").mkdir()
    ctx, seen = _ctx()
    with pytest.raises(ValueError, match="outside the download root"):
        mail.export_messages(ctx, str(tmp_path / "elsewhere"), message_ids=["m1"])
    assert not seen


# --- eml and attachments ----------------------------------------------------

def test_eml_alongside_shares_the_stem(tmp_path):
    ctx, _ = _ctx()
    r = mail.export_messages(ctx, str(tmp_path), message_ids=["m1"], eml=True)
    stem = r["results"][0]["name"].removesuffix(".md")
    assert (tmp_path / f"{stem}.eml").read_bytes().startswith(b"Message-ID: <m1@")


def test_attachments_land_in_a_folder_named_for_the_record(tmp_path, downloads):
    ctx, _ = _ctx()
    r = mail.export_messages(ctx, str(tmp_path), message_ids=["m1", "m2"],
                             attachments=True)
    stem = by_id(r)["m1"]["name"].removesuffix(".md")
    assert downloads == [("m1", str(tmp_path / stem), "a1")]     # inline a2 skipped
    assert (tmp_path / stem).is_dir()
    assert by_id(r)["m1"]["attachments"] == 1 and by_id(r)["m2"]["attachments"] == 0


def test_no_attachments_unless_asked(tmp_path, downloads):
    ctx, _ = _ctx()
    mail.export_messages(ctx, str(tmp_path), message_ids=["m1"])
    assert downloads == []


def test_full_body_is_passed_through(tmp_path):
    ctx, _ = _ctx()
    r = mail.export_messages(ctx, str(tmp_path), message_ids=["m1"], full_body=True)
    text = (tmp_path / r["results"][0]["name"]).read_text()
    assert "Body of m1." in text and 'body_scope: "full"' in text


# --- shape ------------------------------------------------------------------

def test_result_shape(tmp_path):
    ctx, _ = _ctx()
    r = mail.export_messages(ctx, str(tmp_path), conversation_id=CONV)
    assert set(r) == {"dir", "dry_run", "results", "counts", "truncated"}
    for x in r["results"]:
        assert set(x) == {"message_id", "internet_message_id", "name", "outcome",
                          "detail", "attachments"}
    assert sum(r["counts"].values()) == len(r["results"])


def test_registered_as_a_read_tier_mail_tool():
    from ckm365 import tools
    assert mail.export_messages in tools.READ["mail"]
    assert mail.export_messages not in tools.WRITE["mail"]
