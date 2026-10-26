"""Offline tests for migrate_correspondence, the apply step of mr31re.

It takes the planner's output and applies the actions that can be
applied — upgrade (rewrite an OKF v0.1 record's front matter to v0.2,
body kept), pair (write the .md record beside a lone .eml, located in
Graph by RFC 5322 Message-ID) and backfill-id (add the Message-ID a
hand-written sidecar lacks, from its paired .eml). dry_run is the default
and does the lookups but writes nothing. Nothing is ever deleted, no
body is ever rewritten (6v3d56: a person may have written below the
mail), and a second run changes nothing.
"""

import re

import httpx
import pytest

migrate = pytest.importorskip("ckm365.tools.mail.migrate")
if not hasattr(migrate, "migrate_correspondence"):
    pytest.skip("migrate_correspondence not built yet", allow_module_level=True)

from ckm365 import __version__  # noqa: E402
from ckm365.config import Profile  # noqa: E402
from ckm365.graph import Graph  # noqa: E402
from ckm365.tools import Ctx, mail  # noqa: E402
from test_mail_migrate import ID1, ID2, ID3, eml, hand, v01, v02  # noqa: E402

MAILBOX = "operator@tenant-a.example"
SHARED = "shared@tenant-a.example"
KNOWN = {ID1: "m1", ID2: "m2", ID3: "m3"}   # Message-ID -> Graph id


class FakeAuth:
    def token(self):
        return "fake-token"

    def username(self):
        return MAILBOX


def _message(mid, imid):
    return {"id": mid, "subject": f"Subject {mid}",
            "from": {"emailAddress": {"address": "other-user@tenant-b.example"}},
            "toRecipients": [{"emailAddress": {"address": MAILBOX}}],
            "receivedDateTime": "2026-10-01T01:02:03Z",
            "body": {"contentType": "text", "content": f"Body of {mid}."},
            "bodyPreview": f"Body of {mid}.", "internetMessageId": imid,
            "webLink": f"https://outlook.example/{mid}",
            "hasAttachments": False, "isRead": True, "isDraft": False,
            "parentFolderId": "INBOX"}


def _ctx(known=KNOWN, fail_get=()):
    """A Graph that answers the Message-ID filter from `known`, serves the
    message by id, and 404s the ids in fail_get. Records every request."""
    seen = []

    def handler(request):
        seen.append(request)
        path = request.url.path
        if path.endswith("/mailFolders/sentitems"):
            return httpx.Response(200, json={"id": "SENTITEMS"})
        if path.endswith("/attachments"):
            return httpx.Response(200, json={"value": []})
        if path.endswith("/messages"):
            m = re.search(r"internetMessageId eq '(.*)'",
                          request.url.params.get("$filter", ""))
            imid = m.group(1).replace("''", "'") if m else None
            mid = known.get(imid)
            return httpx.Response(200, json={"value": [{"id": mid}] if mid else []})
        mid = path.rsplit("/", 1)[-1]
        if mid in fail_get:
            return httpx.Response(404, json={"error": {
                "code": "ErrorItemNotFound", "message": "gone"}})
        imid = next(k for k, v in known.items() if v == mid)
        return httpx.Response(200, json=_message(mid, imid))

    ctx = Ctx(profiles={"tenant-a": Profile(
        name="tenant-a", tenant_id="t1", client_id="c1",
        default_mailbox=MAILBOX)})
    ctx.set_graph("tenant-a", Graph(FakeAuth(),
                                    transport=httpx.MockTransport(handler)))
    return ctx, seen


def _folder(tmp_path):
    """One of everything the apply step handles, plus what it must not touch."""
    (tmp_path / "old.md").write_text(v01(ID1))          # upgrade
    (tmp_path / "evidence.eml").write_bytes(eml(ID2))   # pair
    (tmp_path / "notes.md").write_text(hand())          # backfill-id ...
    (tmp_path / "notes.eml").write_bytes(eml(ID3))      # ... from this
    (tmp_path / "loose.md").write_text("# no front matter\n")   # manual
    return tmp_path


def snapshot(folder):
    return {p.name: p.read_bytes() for p in folder.iterdir() if p.is_file()}


def by_name(result):
    return {r["name"]: r for r in result["results"]}


# --- dry run (the default) --------------------------------------------------

def test_dry_run_looks_up_but_writes_nothing(tmp_path):
    (tmp_path / "old.md").write_text(v01(ID1))
    (tmp_path / "evidence.eml").write_bytes(eml(ID2))
    (tmp_path / "notes.md").write_text(hand())
    (tmp_path / "notes.eml").write_bytes(eml(ID3))
    ctx, seen = _ctx()
    before = snapshot(tmp_path)
    result = migrate.migrate_correspondence(ctx, str(tmp_path))
    assert result["dry_run"] is True
    r = by_name(result)
    assert r["old.md"] == {"name": "old.md", "action": "upgrade",
                           "outcome": "would-apply", "detail": r["old.md"]["detail"]}
    assert "body kept" in r["old.md"]["detail"]
    assert r["evidence.eml"]["outcome"] == "would-apply"
    assert r["notes.md"]["outcome"] == "would-apply"
    assert snapshot(tmp_path) == before
    # the pair lookup happened (so a dry run can say "not found"), nothing
    # else: upgrade and backfill-id are local rewrites
    assert all(req.method == "GET" for req in seen)
    filters = [req.url.params.get("$filter", "") for req in seen]
    assert any(ID2 in f for f in filters) and not any(ID1 in f for f in filters)


def test_dry_run_reports_a_message_graph_cannot_find(tmp_path):
    (tmp_path / "evidence.eml").write_bytes(eml("<gone@tenant-b.example>"))
    ctx, _ = _ctx()
    r = by_name(migrate.migrate_correspondence(ctx, str(tmp_path)))["evidence.eml"]
    assert r["outcome"] == "not-found"
    assert "not found" in r["detail"].lower()


# --- applying ---------------------------------------------------------------

def test_upgrade_rewrites_only_the_front_matter_of_a_v01_record(tmp_path):
    (tmp_path / "old.md").write_text(v01(ID1))
    ctx, seen = _ctx()
    result = migrate.migrate_correspondence(ctx, str(tmp_path), dry_run=False)
    assert by_name(result)["old.md"]["outcome"] == "applied"
    text = (tmp_path / "old.md").read_text()
    head, _, body = text.partition("\n---\n")
    assert (f'generated: {{by: "ckm365/{__version__}", '
            'at: "2026-10-01T01:02:03Z"}') in head       # at: the old timestamp
    assert f'internet_message_id: "{ID1}"' in head
    assert 'mailbox: "operator@tenant-a.example"' in head  # other keys survive
    assert "timestamp:" not in head and "exported_by:" not in head
    assert body == v01(ID1).partition("\n---\n")[2]       # body byte for byte
    assert not seen                                      # no Graph call
    assert sorted(p.name for p in tmp_path.iterdir()) == ["old.md"]  # no .part


def test_upgrade_keeps_hand_written_sections_below_the_body(tmp_path):
    # 6v3d56: on a real folder, 6 of 18 v0.1 records carried summaries and
    # action tables a person had added after export. They must survive.
    annotated = v01(ID1) + ("\n## Summary\n\nWhat to remember.\n\n"
                            "| Owner | Action |\n|---|---|\n| me | reply |\n")
    (tmp_path / "old.md").write_text(annotated)
    ctx, _ = _ctx()
    dry = by_name(migrate.migrate_correspondence(ctx, str(tmp_path)))["old.md"]
    assert dry["outcome"] == "would-apply" and "body kept" in dry["detail"]
    assert (tmp_path / "old.md").read_text() == annotated
    migrate.migrate_correspondence(ctx, str(tmp_path), dry_run=False)
    text = (tmp_path / "old.md").read_text()
    assert text.partition("\n---\n")[2] == annotated.partition("\n---\n")[2]
    assert "## Summary" in text and "| me | reply |" in text
    assert "timestamp:" not in text


def test_upgrade_preserves_crlf_line_endings(tmp_path):
    (tmp_path / "old.md").write_bytes(v01(ID1).replace("\n", "\r\n").encode())
    ctx, _ = _ctx()
    migrate.migrate_correspondence(ctx, str(tmp_path), dry_run=False)
    data = (tmp_path / "old.md").read_bytes()
    assert b"\n" not in data.replace(b"\r\n", b"")
    assert b"generated: {by:" in data and b"timestamp:" not in data


def test_upgrade_fails_cleanly_on_a_v01_record_without_timestamp(tmp_path):
    (tmp_path / "old.md").write_text(v01(ID1).replace(
        'timestamp: "2026-10-01T01:02:03Z"\n', ""))
    ctx, _ = _ctx()
    before = snapshot(tmp_path)
    r = by_name(migrate.migrate_correspondence(ctx, str(tmp_path), dry_run=False))
    assert r["old.md"]["outcome"] == "failed" and "timestamp" in r["old.md"]["detail"]
    assert snapshot(tmp_path) == before


def test_pair_writes_the_record_beside_a_lone_eml(tmp_path):
    (tmp_path / "evidence.eml").write_bytes(eml(ID2))
    ctx, _ = _ctx()
    result = migrate.migrate_correspondence(ctx, str(tmp_path), dry_run=False)
    r = by_name(result)["evidence.eml"]
    assert r["outcome"] == "applied"
    assert "evidence.md" in r["detail"]
    text = (tmp_path / "evidence.md").read_text()
    assert f'internet_message_id: "{ID2}"' in text and "Body of m2." in text
    assert (tmp_path / "evidence.eml").read_bytes() == eml(ID2)


def test_pair_refuses_a_name_that_is_taken(tmp_path):
    (tmp_path / "q.eml").write_bytes(eml(ID2))
    (tmp_path / "q.md").write_text(v02(ID1))         # same stem, OTHER message
    ctx, _ = _ctx()
    before = snapshot(tmp_path)
    r = by_name(migrate.migrate_correspondence(ctx, str(tmp_path),
                                               dry_run=False))["q.eml"]
    assert r["outcome"] == "failed"
    assert "q.md" in r["detail"]
    assert snapshot(tmp_path) == before


def test_backfill_adds_the_id_and_keeps_the_hand_written_body_byte_for_byte(tmp_path):
    (tmp_path / "notes.md").write_text(hand())
    (tmp_path / "notes.eml").write_bytes(eml(ID3))
    ctx, seen = _ctx()
    result = migrate.migrate_correspondence(ctx, str(tmp_path), dry_run=False)
    assert by_name(result)["notes.md"]["outcome"] == "applied"
    text = (tmp_path / "notes.md").read_text()
    head, _, body = text.partition("\n---\n")
    assert f'internet_message_id: "{ID3}"' in head
    assert "subject: Q1 figures" in head               # their keys survive
    assert body == hand().partition("\n---\n")[2]       # body untouched
    assert not seen                                     # no Graph call needed


def test_pair_looks_up_the_selected_mailbox(tmp_path):
    (tmp_path / "evidence.eml").write_bytes(eml(ID2))
    ctx, seen = _ctx()
    migrate.migrate_correspondence(ctx, str(tmp_path), mailbox=SHARED)
    first = next(req for req in seen if "$filter" in req.url.params)
    assert f"/users/{SHARED}/messages" in first.url.path


def test_a_failure_on_one_file_does_not_stop_the_others_or_leave_residue(tmp_path):
    (tmp_path / "a.eml").write_bytes(eml(ID1))
    (tmp_path / "b.eml").write_bytes(eml(ID2))
    ctx, _ = _ctx(fail_get=("m1",))
    result = migrate.migrate_correspondence(ctx, str(tmp_path), dry_run=False)
    r = by_name(result)
    assert r["a.eml"]["outcome"] == "failed"
    assert "404" in r["a.eml"]["detail"] or "ErrorItemNotFound" in r["a.eml"]["detail"]
    assert r["b.eml"]["outcome"] == "applied"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["a.eml", "b.eml", "b.md"]


# --- what it never does -----------------------------------------------------

def test_duplicates_and_manual_items_are_reported_never_touched(tmp_path):
    (tmp_path / "a.md").write_text(v02(ID1))
    (tmp_path / "b.md").write_text(v02(ID1))              # flag-duplicate
    (tmp_path / "loose.md").write_text("# no front matter\n")   # manual
    (tmp_path / "x.msg").write_bytes(b"\0" * 8)             # manual
    ctx, seen = _ctx()
    before = snapshot(tmp_path)
    r = by_name(migrate.migrate_correspondence(ctx, str(tmp_path), dry_run=False))
    assert r["b.md"]["action"] == "flag-duplicate" and r["b.md"]["outcome"] == "skipped"
    assert r["loose.md"]["outcome"] == "skipped" and r["x.msg"]["outcome"] == "skipped"
    assert "a.md" not in r                                   # action none: not listed
    assert snapshot(tmp_path) == before
    assert not seen


def test_actions_subset_applies_only_those(tmp_path):
    (tmp_path / "old.md").write_text(v01(ID1))
    (tmp_path / "evidence.eml").write_bytes(eml(ID2))
    ctx, _ = _ctx()
    r = by_name(migrate.migrate_correspondence(ctx, str(tmp_path), actions=["pair"],
                                               dry_run=False))
    assert r["evidence.eml"]["outcome"] == "applied"
    assert r["old.md"]["outcome"] == "skipped"
    assert "timestamp:" in (tmp_path / "old.md").read_text()


def test_unknown_action_is_an_error(tmp_path):
    ctx, _ = _ctx()
    with pytest.raises(ValueError, match="actions"):
        migrate.migrate_correspondence(ctx, str(tmp_path), actions=["delete"])


def test_second_run_changes_nothing(tmp_path):
    _folder(tmp_path)
    ctx, _ = _ctx()
    first = migrate.migrate_correspondence(ctx, str(tmp_path), dry_run=False)
    assert first["counts"]["applied"] == 3
    after_first = snapshot(tmp_path)
    second = migrate.migrate_correspondence(ctx, str(tmp_path), dry_run=False)
    assert "applied" not in second["counts"]
    assert snapshot(tmp_path) == after_first
    assert len(after_first) >= len(snapshot(tmp_path))      # never fewer files


def test_result_shape_and_counts(tmp_path):
    _folder(tmp_path)
    ctx, _ = _ctx()
    result = migrate.migrate_correspondence(ctx, str(tmp_path))
    assert set(result) == {"dir", "dry_run", "results", "counts"}
    assert result["dir"] == str(tmp_path.resolve())
    for r in result["results"]:
        assert set(r) == {"name", "action", "outcome", "detail"}
        assert r["action"] != "none"
    assert sum(result["counts"].values()) == len(result["results"])


def test_dir_is_fenced_by_the_download_root(tmp_path, monkeypatch):
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    monkeypatch.setenv("CKM365_DOWNLOAD_ROOT", str(tmp_path / "root"))
    (tmp_path / "root").mkdir()
    ctx, _ = _ctx()
    with pytest.raises(ValueError, match="outside the download root"):
        migrate.migrate_correspondence(ctx, str(outside))


def test_registered_as_a_read_tier_mail_tool():
    from ckm365 import tools
    assert mail.migrate_correspondence is migrate.migrate_correspondence
    assert migrate.migrate_correspondence in tools.READ["mail"]
    assert migrate.migrate_correspondence not in tools.WRITE["mail"]
