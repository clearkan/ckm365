"""Offline spec for bringing pre-CKM-49 records up to date (tvtrb0, step 2).

Records written by v2.8.0-v2.11.x are OKF v0.2 but lack what CKM-49
added: `type: "Email"` instead of `"Message"` + `channel: "email"`, a
per-mailbox webLink as `resource` instead of `mid:`, no thread keys, and
a body that is the FULL quoted chain. The planner calls them version
"okf-0.2-email" and proposes `upgrade`; the apply step brings them up to
date WITHOUT touching the body (6v3d56: a person may have written below
the mail):

- type "Email" -> "Message", and `channel: "email"` right after it;
- resource: the `mid:` URI of internet_message_id; the old URL moves to
  `web_link` (just before body_scope);
- conversation_id, in_reply_to, references: fetched from Graph (metadata
  only: `$select=conversationId,internetMessageHeaders`, never a body),
  inserted right after internet_message_id;
- body_scope: "full", because that is what the old body is, inserted
  just before has_attachments;
- generated: `by` becomes this version, `at` is kept.

The message is found by Message-ID, the record's own `mailbox` first,
then the selected one (the step 2.10.1 dropped comes back, because this
upgrade needs Graph). Not found: outcome not-found, file untouched, and a
later run can try again. An OKF v0.1 record gets both upgrades in one
write. A hand-written front matter typed "Message" is mail when its
channel is email or absent, a note otherwise.

Skipped as a module until the planner recognises okf-0.2-email.
"""

import json
import re
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

migrate = pytest.importorskip("ckm365.tools.mail.migrate")


def _knows_ckm49() -> bool:
    from test_mail_migrate import v02_email
    with tempfile.TemporaryDirectory() as d, pytest.MonkeyPatch.context() as env:
        # Collection runs before conftest's disk/state fixtures.
        env.setenv("CKM365_DOWNLOAD_ROOT", d)
        env.setenv("XDG_STATE_HOME", str(Path(d, "state")))
        Path(d, "r.md").write_text(v02_email())
        return migrate.plan_correspondence_migration(None, d)["items"][0]["action"] == "upgrade"


if not _knows_ckm49():
    pytest.skip("planner does not upgrade pre-CKM-49 records yet (tvtrb0)",
                allow_module_level=True)

from ckm365 import __version__  # noqa: E402
from ckm365.config import Profile  # noqa: E402
from ckm365.graph import Graph  # noqa: E402
from ckm365.tools import Ctx  # noqa: E402
from test_mail_migrate import ID1, ID2, by_name, plan, v01, v02, v02_email  # noqa: E402

MAILBOX = "operator@tenant-a.example"
SHARED = "shared@tenant-a.example"
CONV = "AAQkADconv" + "c" * 70
PARENT = "<parent@tenant-b.example>"
ROOT = "<root@tenant-b.example>"
ANNOTATION = "\n## Summary\n\nWhat to remember.\n\n| Owner | Action |\n|---|---|\n| me | reply |\n"
NEW_ORDER = ["type", "channel", "title", "description", "resource", "tags",
             "generated", "from", "to", "cc", "mailbox", "message_id",
             "internet_message_id", "conversation_id", "in_reply_to",
             "references", "web_link", "body_scope", "has_attachments",
             "is_bulk", "is_auto_reply"]


class FakeAuth:
    def token(self):
        return "fake-token"

    def username(self):
        return MAILBOX


def _ctx(known=None, where=MAILBOX, invalid=()):
    """Answers the Message-ID filter in mailbox `where` only, and serves
    thread metadata for the ids it knows. Records every request."""
    known = known if known is not None else {ID1: "m1", ID2: "m2"}
    seen = []

    def handler(request):
        seen.append(request)
        path = request.url.path
        if any(f"/users/{x}/" in path for x in invalid):
            return httpx.Response(404, json={"error": {
                "code": "ErrorInvalidUser", "message": "invalid user"}})
        q = {k: v[0] for k, v in parse_qs(urlsplit(str(request.url)).query).items()}
        if path.endswith("/messages"):
            m = re.search(r"internetMessageId eq '(.*)'", q.get("$filter", ""))
            imid = m.group(1).replace("''", "'") if m else None
            hit = known.get(imid) if f"/users/{where}/" in path else None
            return httpx.Response(200, json={"value": [{"id": hit}] if hit else []})
        return httpx.Response(200, json={
            "id": path.rsplit("/", 1)[-1], "conversationId": CONV,
            "internetMessageHeaders": [
                {"name": "In-Reply-To", "value": PARENT},
                {"name": "References", "value": f"{ROOT} {PARENT}"}]})

    ctx = Ctx(profiles={"tenant-a": Profile(
        name="tenant-a", tenant_id="t1", client_id="c1", default_mailbox=MAILBOX)})
    ctx.set_graph("tenant-a", Graph(FakeAuth(), transport=httpx.MockTransport(handler)))
    return ctx, seen


def front(text):
    head = text.partition("\n---\n")[0].splitlines()[1:]
    return [tuple(line.split(": ", 1)) for line in head]


def results(ctx, folder, **kw):
    out = migrate.migrate_correspondence(ctx, str(folder), **kw)
    return {r["name"]: r for r in out["results"]}


# --- the planner ------------------------------------------------------------

def test_a_pre_ckm49_record_is_an_upgrade(tmp_path):
    (tmp_path / "old.md").write_text(v02_email())
    item = by_name(plan(tmp_path))["old.md"]
    assert item["version"] == "okf-0.2-email" and item["action"] == "upgrade"


def test_a_current_record_needs_nothing(tmp_path):
    (tmp_path / "cur.md").write_text(v02())
    item = by_name(plan(tmp_path))["cur.md"]
    assert item["version"] == "okf-0.2" and item["action"] == "none"


@pytest.mark.parametrize("extra,action", [
    ('channel: email\n', "manual"),          # mail without an id: manual
    ('', "manual"),                          # no channel: still mail
    ('channel: whatsapp\n', "note"),         # a chat record: not mail
])
def test_hand_written_type_message_follows_its_channel(tmp_path, extra, action):
    (tmp_path / "h.md").write_text(f"---\ntype: Message\n{extra}title: x\n---\n\nmine\n")
    assert by_name(plan(tmp_path))["h.md"]["action"] == action


# --- the apply step ---------------------------------------------------------

def test_upgrade_brings_the_front_matter_up_to_date_and_keeps_the_body(tmp_path):
    (tmp_path / "old.md").write_text(v02_email() + ANNOTATION)
    ctx, seen = _ctx()
    r = results(ctx, tmp_path, dry_run=False)["old.md"]
    assert r["outcome"] == "applied"
    text = (tmp_path / "old.md").read_text()
    kv = dict(front(text))
    assert [k for k, _ in front(text)] == NEW_ORDER
    assert kv["type"] == '"Message"' and kv["channel"] == '"email"'
    assert kv["resource"] == f'"mid:{ID1.strip("<>")}"'
    assert kv["web_link"] == '"https://outlook.example/x"'
    assert kv["conversation_id"] == f'"{CONV}"'
    assert kv["in_reply_to"] == f'"{PARENT}"'
    assert kv["references"] == f'["{ROOT}", "{PARENT}"]'
    assert kv["body_scope"] == '"full"'
    assert kv["generated"] == f'{{by: "ckm365/{__version__}", at: "2026-10-01T01:02:03Z"}}'
    assert kv["title"] == '"Q1 figures"' and kv["mailbox"] == f'"{MAILBOX}"'
    old_body = (v02_email() + ANNOTATION).partition("\n---\n")[2]
    assert text.partition("\n---\n")[2] == old_body             # byte for byte
    assert "body kept" in r["detail"]


def test_the_lookup_reads_metadata_never_a_body(tmp_path):
    (tmp_path / "old.md").write_text(v02_email())
    ctx, seen = _ctx()
    results(ctx, tmp_path, dry_run=False)
    gets = [q for q in seen if not q.url.path.endswith("/messages")]
    assert len(gets) == 1
    select = parse_qs(urlsplit(str(gets[0].url)).query)["$select"][0]
    assert set(select.split(",")) == {"conversationId", "internetMessageHeaders"}


def test_dry_run_looks_up_and_writes_nothing(tmp_path):
    (tmp_path / "old.md").write_text(v02_email())
    before = (tmp_path / "old.md").read_bytes()
    ctx, seen = _ctx()
    r = results(ctx, tmp_path)["old.md"]
    assert r["outcome"] == "would-apply" and "body kept" in r["detail"]
    assert (tmp_path / "old.md").read_bytes() == before
    assert any("$filter" in q.url.params for q in seen)


def test_not_found_leaves_the_file_alone(tmp_path):
    (tmp_path / "old.md").write_text(v02_email())
    before = (tmp_path / "old.md").read_bytes()
    ctx, _ = _ctx(known={})
    r = results(ctx, tmp_path, dry_run=False)["old.md"]
    assert r["outcome"] == "not-found"
    assert (tmp_path / "old.md").read_bytes() == before


def test_the_records_own_mailbox_is_tried_first(tmp_path):
    (tmp_path / "old.md").write_text(v02_email().replace(
        f'mailbox: "{MAILBOX}"', f'mailbox: "{SHARED}"'))
    ctx, seen = _ctx(where=SHARED)
    r = results(ctx, tmp_path, dry_run=False)["old.md"]
    assert r["outcome"] == "applied"
    first = next(q for q in seen if "$filter" in q.url.params)
    assert f"/users/{SHARED}/messages" in first.url.path


def test_an_unknown_own_mailbox_falls_through_to_the_selected_one(tmp_path):
    # Live, 2026-11-07: records exported from one tenant name a mailbox the
    # other tenant's profile cannot see; Graph answers 404 ErrorInvalidUser.
    (tmp_path / "old.md").write_text(v02_email().replace(
        f'mailbox: "{MAILBOX}"', 'mailbox: "someone@tenant-b.example"'))
    ctx, seen = _ctx(invalid=("someone@tenant-b.example",))
    r = results(ctx, tmp_path, dry_run=False)["old.md"]
    assert r["outcome"] == "applied"
    assert any("/users/someone@tenant-b.example/" in q.url.path for q in seen)


def test_a_v01_record_is_brought_fully_current_in_one_write(tmp_path):
    (tmp_path / "old.md").write_text(v01(ID2) + ANNOTATION)
    ctx, _ = _ctx()
    assert results(ctx, tmp_path, dry_run=False)["old.md"]["outcome"] == "applied"
    text = (tmp_path / "old.md").read_text()
    keys = [k for k, _ in front(text)]
    assert "timestamp" not in keys and "exported_by" not in keys
    assert dict(front(text))["type"] == '"Message"'
    assert dict(front(text))["body_scope"] == '"full"'
    assert text.endswith(ANNOTATION)
    assert by_name(plan(tmp_path))["old.md"]["action"] == "none"


def test_a_second_run_changes_nothing(tmp_path):
    (tmp_path / "a.md").write_text(v02_email(ID1))
    (tmp_path / "b.md").write_text(v01(ID2))
    ctx, _ = _ctx()
    migrate.migrate_correspondence(ctx, str(tmp_path), dry_run=False)
    after = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    second = migrate.migrate_correspondence(ctx, str(tmp_path), dry_run=False)
    assert second["results"] == []
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == after


def test_crlf_records_stay_crlf(tmp_path):
    (tmp_path / "old.md").write_bytes(v02_email().replace("\n", "\r\n").encode())
    ctx, _ = _ctx()
    results(ctx, tmp_path, dry_run=False)
    data = (tmp_path / "old.md").read_bytes()
    assert b"\n" not in data.replace(b"\r\n", b"")
    assert b'channel: "email"' in data


def test_a_record_without_a_message_id_is_manual_not_upgraded(tmp_path):
    (tmp_path / "old.md").write_text(v02_email(imid=None))
    item = by_name(plan(tmp_path))["old.md"]
    assert item["action"] == "manual" and "Message-ID" in item["reason"]
