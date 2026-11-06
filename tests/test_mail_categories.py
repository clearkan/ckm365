"""Offline spec for set_categories (g669gd, CKM-51): add or remove Outlook
categories on messages, in one batch.

Asked for by a session that tagged every message filed into a git repo
with an "In git" category and had to use the graph-direct escape hatch.

- Write tier, beside mark_read/flag in triage.py: categories are message
  METADATA, like read state and flags, so this is not a content edit and
  does not cut against the draft-only rule.
- Graph's `categories` PATCH REPLACES the whole list, so the tool reads
  first (a batched GET, `$select=categories`), merges, then PATCHes only
  the messages whose list actually changed. Last write wins if Outlook
  edits the list in between; the docstring says so.
- Names compare CASE-INSENSITIVELY (Outlook treats them that way): adding
  "in git" to a message tagged "In git" is no change, and remove drops
  any casing. Existing order is kept; added names go on the end in the
  order given.
- For names in `add`, a missing MASTER category (the mailbox's list,
  which carries the colour) is created with POST outlook/masterCategories.
  That needs MailboxSettings.ReadWrite, which ckm365 does not request, so
  a refusal is a WARNING in the result, never a failure: the labels on
  the messages are the point; the colour is a nicety.

Skipped as a module until mail.set_categories exists.
"""

import json

import httpx
import pytest

from ckm365.tools import mail

if not hasattr(mail, "set_categories"):
    pytest.skip("set_categories not built yet (g669gd)", allow_module_level=True)

from ckm365.config import Profile  # noqa: E402
from ckm365.graph import Graph  # noqa: E402
from ckm365.tools import Ctx, WriteDisabled  # noqa: E402

MAILBOX = "user@tenant-a.example"
MASTER = "/outlook/masterCategories"  # the path suffix the tool must call


class FakeAuth:
    def token(self):
        return "fake-token"

    def username(self):
        return MAILBOX


class FakeTenant:
    """A mailbox with per-message category lists and a master list.

    Records every /$batch sub-request and every master-category call, so a
    test can assert what was (and was NOT) sent.
    """

    def __init__(self, messages, master=("Red category",), *,
                 get_status=None, patch_status=None,
                 master_get_status=200, master_post_status=201):
        self.messages = {k: list(v) for k, v in messages.items()}
        self.master = list(master)
        self.get_status = get_status or {}
        self.patch_status = patch_status or {}
        self.master_get_status = master_get_status
        self.master_post_status = master_post_status
        self.batches = []   # one list of sub-requests per /$batch call
        self.master_calls = []  # (method, body or None)

    def _sub(self, r):
        mid = r["url"].split("/messages/", 1)[1].split("?", 1)[0]
        if r["method"] == "GET":
            assert "$select=categories" in r["url"]
            status = self.get_status.get(mid, 200 if mid in self.messages else 404)
            body = ({"id": mid, "categories": self.messages[mid]}
                    if status == 200 else
                    {"error": {"code": "ErrorItemNotFound", "message": "gone"}})
            return status, body
        assert r["method"] == "PATCH", r
        assert set(r["body"]) == {"categories"}  # metadata only, never more
        status = self.patch_status.get(mid, 200)
        if status == 200:
            self.messages[mid] = list(r["body"]["categories"])
            return 200, {"id": mid, "categories": self.messages[mid]}
        return status, {"error": {"code": "ErrorAccessDenied", "message": "no"}}

    def __call__(self, request):
        path = request.url.path
        if path.endswith("/$batch"):
            reqs = json.loads(request.content)["requests"]
            self.batches.append(reqs)
            out = []
            for r in reqs:
                status, body = self._sub(r)
                out.append({"id": r["id"], "status": status, "body": body})
            return httpx.Response(200, json={"responses": out[::-1]})
        if path.endswith(MASTER):
            if request.method == "GET":
                self.master_calls.append(("GET", None))
                if self.master_get_status != 200:
                    return httpx.Response(self.master_get_status, json={
                        "error": {"code": "ErrorAccessDenied",
                                  "message": "Access is denied."}})
                return httpx.Response(200, json={"value": [
                    {"id": f"cat{i}", "displayName": n, "color": "preset0"}
                    for i, n in enumerate(self.master)]})
            body = json.loads(request.content)
            self.master_calls.append(("POST", body))
            if self.master_post_status != 201:
                return httpx.Response(self.master_post_status, json={
                    "error": {"code": "ErrorAccessDenied",
                              "message": "Access is denied."}})
            self.master.append(body["displayName"])
            return httpx.Response(201, json={"id": "new", **body})
        raise AssertionError(f"unexpected request {request.method} {request.url}")

    @property
    def patches(self):
        return [r for b in self.batches for r in b if r["method"] == "PATCH"]


def _ctx(tenant, *, write=True):
    profiles = {"tenant-a": Profile(name="tenant-a", tenant_id="t1",
                                    client_id="c1", default_mailbox=MAILBOX)}
    ctx = Ctx(profiles=profiles, write_enabled=write)
    ctx.set_graph("tenant-a", Graph(FakeAuth(),
                                    transport=httpx.MockTransport(tenant)))
    return ctx


# --- the merge ------------------------------------------------------------

def test_add_reads_then_patches_the_merged_list():
    t = FakeTenant({"m1": ["Red category"], "m2": []})
    res = mail.set_categories(_ctx(t), ["m1", "m2"], add=["In git"])
    assert [r["method"] for r in t.batches[0]] == ["GET", "GET"]
    assert [r["method"] for r in t.batches[1]] == ["PATCH", "PATCH"]
    assert t.messages == {"m1": ["Red category", "In git"], "m2": ["In git"]}
    assert res["ok"] == 2
    assert res["unchanged"] == 0
    assert res["failed"] == []
    assert res["categories"] == {"m1": ["Red category", "In git"],
                                 "m2": ["In git"]}


def test_unchanged_messages_are_not_patched_case_insensitively():
    t = FakeTenant({"m1": ["IN GIT"], "m2": ["Blue"]})
    res = mail.set_categories(_ctx(t), ["m1", "m2"], add=["in git"])
    assert [p["url"].split("/")[-1] for p in t.patches] == ["m2"]
    assert t.messages["m1"] == ["IN GIT"]  # existing casing kept
    assert t.messages["m2"] == ["Blue", "in git"]
    assert (res["ok"], res["unchanged"]) == (1, 1)
    assert res["categories"]["m1"] == ["IN GIT"]


def test_nothing_to_change_sends_no_patch_batch_at_all():
    t = FakeTenant({"m1": ["In git"]})
    res = mail.set_categories(_ctx(t), ["m1"], add=["In git"])
    assert len(t.batches) == 1 and t.patches == []
    assert (res["ok"], res["unchanged"]) == (0, 1)


def test_remove_drops_any_casing_and_keeps_the_rest_in_order():
    t = FakeTenant({"m1": ["A", "in git", "B"], "m2": ["C"]})
    res = mail.set_categories(_ctx(t), ["m1", "m2"], remove=["In Git"])
    assert t.messages == {"m1": ["A", "B"], "m2": ["C"]}
    assert (res["ok"], res["unchanged"]) == (1, 1)


def test_add_and_remove_together():
    t = FakeTenant({"m1": ["Todo", "X"]})
    mail.set_categories(_ctx(t), ["m1"], add=["Done", "done"], remove=["todo"])
    assert t.messages["m1"] == ["X", "Done"]  # add de-duplicated, first wins


# --- per-message failure --------------------------------------------------

def test_failures_are_per_message_and_never_abort_the_batch():
    t = FakeTenant({"m1": [], "m3": []}, patch_status={"m3": 403})
    res = mail.set_categories(_ctx(t), ["m1", "m2", "m3"], add=["Tag"])
    # m2 failed its read, so it is never patched; m3 failed its patch.
    assert [p["url"].split("/")[-1] for p in t.patches] == ["m1", "m3"]
    assert res["ok"] == 1
    assert sorted(f["id"] for f in res["failed"]) == ["m2", "m3"]
    assert all(f["error"] for f in res["failed"])
    assert set(res["categories"]) == {"m1"}


# --- validation, before any request ---------------------------------------

@pytest.mark.parametrize("kwargs", [
    {},                                   # nothing to do
    {"add": [], "remove": []},
    {"add": ["  "]},                      # blank name
    {"add": "In git"},                    # a bare string, not a list
    {"remove": "In git"},
    {"add": ["Tag"], "remove": ["tag"]},  # the same name both ways
    {"add": ["x" * 256]},                 # longer than Outlook allows
])
def test_invalid_arguments_fail_before_any_request(kwargs):
    t = FakeTenant({"m1": []})
    with pytest.raises(ValueError):
        mail.set_categories(_ctx(t), ["m1"], **kwargs)
    assert t.batches == [] and t.master_calls == []


def test_write_gated():
    t = FakeTenant({"m1": []})
    with pytest.raises(WriteDisabled):
        mail.set_categories(_ctx(t, write=False), ["m1"], add=["Tag"])
    assert t.batches == [] and t.master_calls == []


def test_message_ids_follow_the_triage_convention():
    t = FakeTenant({"m1": []})
    with pytest.raises(ValueError):
        mail.set_categories(_ctx(t), "m1", add=["Tag"])  # bare string
    with pytest.raises(ValueError):
        mail.set_categories(_ctx(t), [], add=["Tag"])


# --- master categories ----------------------------------------------------

def test_missing_master_category_is_created_case_insensitively():
    t = FakeTenant({"m1": []}, master=("red category",))
    res = mail.set_categories(_ctx(t), ["m1"], add=["In git", "Red Category"])
    posts = [b for m, b in t.master_calls if m == "POST"]
    assert [p["displayName"] for p in posts] == ["In git"]
    assert posts[0].get("color")  # Graph requires one
    assert res["master_created"] == ["In git"]
    assert res["master_warning"] is None


def test_master_read_refused_is_a_warning_not_a_failure():
    t = FakeTenant({"m1": []}, master_get_status=403)
    res = mail.set_categories(_ctx(t), ["m1"], add=["In git"])
    assert t.messages["m1"] == ["In git"]  # the label still landed
    assert res["ok"] == 1 and res["failed"] == []
    assert res["master_created"] == []
    assert "MailboxSettings" in res["master_warning"]
    assert [m for m, _ in t.master_calls] == ["GET"]  # no blind POST


def test_master_create_refused_is_a_warning_not_a_failure():
    t = FakeTenant({"m1": []}, master_post_status=403)
    res = mail.set_categories(_ctx(t), ["m1"], add=["In git"])
    assert res["ok"] == 1 and res["failed"] == []
    assert res["master_created"] == []
    assert "In git" in res["master_warning"]


def test_remove_only_never_touches_master_categories():
    t = FakeTenant({"m1": ["Tag"]})
    res = mail.set_categories(_ctx(t), ["m1"], remove=["Tag"])
    assert t.master_calls == []
    assert res["master_created"] == [] and res["master_warning"] is None


def test_no_master_category_when_every_message_failed():
    t = FakeTenant({}, )  # every read 404s
    res = mail.set_categories(_ctx(t), ["m1", "m2"], add=["In git"])
    assert res["ok"] == 0 and len(res["failed"]) == 2
    assert t.master_calls == []  # no side effect for a run that did nothing


def test_registered_as_a_write_tool():
    from ckm365.tools import READ, WRITE
    assert mail.set_categories in WRITE["mail"]
    assert mail.set_categories not in READ["mail"]
