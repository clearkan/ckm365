"""Offline spec for list_mail_folders reaching subfolders (xfccc0).

Mail filed under an Archive tree was unreachable through the tools:
list_mail_folders listed top-level folders only. Now it takes `parent`
(a folder id or well-known name: list that folder's children) and
`recursive` (walk the whole tree below the starting point). Every folder
carries `parent_id` (Graph's parentFolderId) and `path`, its display
names joined with "/" from the starting point down, so "Archive/2025"
reads as a location. Without either argument the call is exactly what it
was: one GET of the top level.
"""

import inspect
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from ckm365.tools import mail

if "recursive" not in inspect.signature(mail.list_mail_folders).parameters:
    pytest.skip("list_mail_folders has no recursive yet (xfccc0)",
                allow_module_level=True)

from ckm365.config import Profile  # noqa: E402
from ckm365.graph import Graph  # noqa: E402
from ckm365.models import MailFolder  # noqa: E402
from ckm365.tools import Ctx  # noqa: E402

MAILBOX = "operator@tenant-a.example"
ROOT = "ROOTID"

# id -> (displayName, parentFolderId)
TREE = {
    "INBOX": ("Inbox", ROOT),
    "ARCH": ("Archive", ROOT),
    "SENT": ("Sent Items", ROOT),
    "A25": ("2025", "ARCH"),
    "A26": ("2026", "ARCH"),
    "A26V": ("Vendor", "A26"),
    "IN-X": ("Projects", "INBOX"),
}


class FakeAuth:
    def token(self):
        return "fake-token"

    def username(self):
        return MAILBOX


def _row(fid):
    name, parent = TREE[fid]
    kids = sum(1 for p in TREE.values() if p[1] == fid)
    return {"id": fid, "displayName": name, "parentFolderId": parent,
            "totalItemCount": 10, "unreadItemCount": 1, "childFolderCount": kids}


def _ctx():
    seen = []
    wk = {"inbox": "INBOX", "archive": "ARCH", "sentitems": "SENT"}

    def handler(request):
        seen.append(request)
        path = request.url.path.removeprefix(f"/v1.0/users/{MAILBOX}/")
        if path == "mailFolders":
            parent = ROOT
        elif path.startswith("mailFolders/") and path.endswith("/childFolders"):
            key = path.split("/")[1]
            parent = wk.get(key, key)
        else:
            return httpx.Response(404, json={"error": {"code": "NotFound", "message": path}})
        return httpx.Response(200, json={"value": [
            _row(fid) for fid, (_, p) in TREE.items() if p == parent]})

    ctx = Ctx(profiles={"tenant-a": Profile(
        name="tenant-a", tenant_id="t1", client_id="c1", default_mailbox=MAILBOX)})
    ctx.set_graph("tenant-a", Graph(FakeAuth(), transport=httpx.MockTransport(handler)))
    return ctx, seen


def test_default_is_the_top_level_in_one_request():
    ctx, seen = _ctx()
    folders = mail.list_mail_folders(ctx)
    assert [f.name for f in folders] == ["Inbox", "Archive", "Sent Items"]
    assert len(seen) == 1
    assert all(isinstance(f, MailFolder) for f in folders)
    assert [f.path for f in folders] == ["Inbox", "Archive", "Sent Items"]
    assert all(f.parent_id == ROOT for f in folders)
    q = parse_qs(urlsplit(str(seen[0].url)).query)
    assert "parentFolderId" in q["$select"][0]


def test_parent_lists_that_folders_children():
    ctx, seen = _ctx()
    folders = mail.list_mail_folders(ctx, parent="ARCH")
    assert [f.name for f in folders] == ["2025", "2026"]
    assert seen[0].url.path.endswith("/mailFolders/ARCH/childFolders")
    assert all(f.parent_id == "ARCH" for f in folders)


def test_parent_takes_a_well_known_name():
    ctx, seen = _ctx()
    folders = mail.list_mail_folders(ctx, parent="archive")
    assert seen[0].url.path.endswith("/mailFolders/archive/childFolders")
    assert [f.name for f in folders] == ["2025", "2026"]


def test_recursive_walks_the_whole_tree_with_paths():
    ctx, _ = _ctx()
    folders = mail.list_mail_folders(ctx, recursive=True)
    paths = [f.path for f in folders]
    assert set(paths) == {"Inbox", "Archive", "Sent Items", "Archive/2025",
                          "Archive/2026", "Archive/2026/Vendor", "Inbox/Projects"}
    by_id = {f.id: f for f in folders}
    for f in folders:                       # every child follows its parent
        if f.parent_id in by_id:
            assert paths.index(by_id[f.parent_id].path) < paths.index(f.path)


def test_recursive_only_asks_for_children_that_exist():
    ctx, seen = _ctx()
    mail.list_mail_folders(ctx, recursive=True)
    asked = sorted(r.url.path.split("/mailFolders/")[1].split("/")[0]
                   for r in seen if r.url.path.endswith("/childFolders"))
    assert asked == ["A26", "ARCH", "INBOX"]          # folders with childFolderCount > 0


def test_recursive_below_a_parent_paths_start_there():
    ctx, _ = _ctx()
    folders = mail.list_mail_folders(ctx, parent="ARCH", recursive=True)
    assert [f.path for f in folders] == ["2025", "2026", "2026/Vendor"]


def test_bad_parent_is_refused_before_any_request():
    ctx, seen = _ctx()
    with pytest.raises(ValueError):
        mail.list_mail_folders(ctx, parent="..")
    assert not seen
