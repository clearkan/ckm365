"""Offline spec for the recipient exclusion list (cw81fa).

Distribution mail takes its recipients from a calendar invite or a
reply-all, and both lag reality: someone who replied "REMOVE", or whose
address now bounces, stays on the invite for weeks. Sending to someone
who opted out is the outcome to prevent, and a calling agent that forgets
to check a list is the failure mode.

The list is a TOML file (stdlib `tomllib`; the issue said YAML, but core
deps stay httpx/msal), named per profile by `exclusions_file` in
profiles.toml:

    [[entries]]
    address = "colleague@tenant-b.example"
    action = "exclude"            # or "warn"; default "exclude"
    type = "opt-out"              # free text: opt-out, bounce, left, ...
    scope = "Co-ordination Meeting"   # optional subject substring
    since = "2026-10-01"          # optional, informational
    until = "2026-12-31"          # optional: entry ignored after this date
    source = "reply 2026-10-01"   # optional, free text
    notes = "asked to be removed" # optional, free text

- Draft tools (create_draft, create_reply_draft, create_forward_draft,
  update_draft, create_persona_reply) still create the draft, with the
  recipients as given, and return `recipient_warnings` listing every
  match. Removing someone silently is worse than flagging them.
- send_draft REFUSES a draft with an `exclude` match unless
  override_exclusions=True. `warn` entries never block.
- check_recipients(addresses, subject=None, exclusions_file=None) is a
  read tool to test a list before building a draft.
- A profile without exclusions_file has the feature off. A configured
  file that is missing or invalid is an ERROR, raised before any Graph
  call: a list that silently fails to load protects nobody.

Skipped as a module until check_recipients exists.
"""

import json
from datetime import date, timedelta

import httpx
import pytest

from ckm365.tools import mail

if not hasattr(mail, "check_recipients"):
    pytest.skip("exclusion list not built yet (cw81fa)", allow_module_level=True)

from ckm365.config import ConfigError, Profile, load_profiles  # noqa: E402
from ckm365.graph import Graph  # noqa: E402
from ckm365.models import Draft, Message, RecipientWarning  # noqa: E402
from ckm365.tools import Ctx  # noqa: E402

MAILBOX = "operator@tenant-a.example"
OPTED = "colleague@tenant-b.example"
BOUNCE = "other-user@tenant-b.example"
OK = "ops@tenant-a.example"
TODAY = date.today()

LIST = f"""
[[entries]]
address = "{OPTED}"
action = "exclude"
type = "opt-out"
source = "replied REMOVE"

[[entries]]
address = "{BOUNCE.upper()}"
action = "warn"
type = "bounce"

[[entries]]
address = "agent@tenant-a.example"
type = "left"
scope = "Co-ordination Meeting"

[[entries]]
address = "old@tenant-b.example"
until = "{(TODAY - timedelta(days=1)).isoformat()}"
"""


class FakeAuth:
    def token(self):
        return "fake-token"

    def username(self):
        return MAILBOX


def _addrs(xs):
    return [{"emailAddress": {"address": a}} for a in xs]


def _graph_draft(to=(), cc=(), bcc=(), subject="Weekly update"):
    return {"id": "d1", "isDraft": True, "@odata.etag": 'W/"1"', "subject": subject,
            "body": {"contentType": "html", "content": "<html><body>x</body></html>"},
            "toRecipients": _addrs(to), "ccRecipients": _addrs(cc),
            "bccRecipients": _addrs(bcc)}


def _ctx(tmp_path, *, text=LIST, configured=True, draft=None, send=False,
         allow_exclusion_override=False):
    """A Graph where every message read/create/patch answers with `draft`
    (or, for POST /messages, echoes what was posted). Records requests."""
    seen = []
    draft = draft or _graph_draft()

    def handler(request):
        seen.append((request.method, request.url.path))
        if request.method == "POST" and request.url.path.endswith("/send"):
            return httpx.Response(202)
        if request.method == "POST" and request.url.path.endswith("/messages"):
            posted = json.loads(request.content)
            return httpx.Response(201, json=_graph_draft(
                to=[r["emailAddress"]["address"] for r in posted.get("toRecipients", [])],
                cc=[r["emailAddress"]["address"] for r in posted.get("ccRecipients", [])],
                bcc=[r["emailAddress"]["address"] for r in posted.get("bccRecipients", [])],
                subject=posted.get("subject", "")))
        return httpx.Response(200, json=draft)

    kw = {"allow_exclusion_override": allow_exclusion_override}
    if configured:
        path = tmp_path / "exclusions.toml"
        if text is not None:
            path.write_text(text)
        kw["exclusions_file"] = str(path)
    ctx = Ctx(profiles={"tenant-a": Profile(
        name="tenant-a", tenant_id="t1", client_id="c1", default_mailbox=MAILBOX, **kw)},
        write_enabled=True, send_enabled=send)
    ctx.set_graph("tenant-a", Graph(FakeAuth(), transport=httpx.MockTransport(handler)))
    return ctx, seen


def addrs(warnings):
    return sorted((w.address.lower(), w.field, w.action) for w in warnings)


# --- check_recipients -------------------------------------------------------

def test_check_reports_matches_case_insensitively(tmp_path):
    ctx, seen = _ctx(tmp_path)
    w = mail.check_recipients(ctx, [OPTED.upper(), BOUNCE, OK])
    assert all(isinstance(x, RecipientWarning) for x in w)
    assert addrs(w) == [(OPTED, "", "exclude"), (BOUNCE, "", "warn")]
    opted = next(x for x in w if x.action == "exclude")
    assert opted.type == "opt-out" and opted.source == "replied REMOVE"
    assert not seen                                    # a local read only


def test_action_defaults_to_exclude(tmp_path):
    ctx, _ = _ctx(tmp_path)
    w = mail.check_recipients(ctx, ["agent@tenant-a.example"],
                              subject="RE: Co-ordination Meeting #12")
    assert [x.action for x in w] == ["exclude"]


def test_scope_is_a_case_insensitive_subject_substring(tmp_path):
    ctx, _ = _ctx(tmp_path)
    who = ["agent@tenant-a.example"]
    assert mail.check_recipients(ctx, who, subject="co-ordination meeting notes")
    assert not mail.check_recipients(ctx, who, subject="Invoice")
    assert not mail.check_recipients(ctx, who)          # scoped, no subject: no match


def test_an_entry_past_its_until_date_is_ignored(tmp_path):
    ctx, _ = _ctx(tmp_path)
    assert mail.check_recipients(ctx, ["old@tenant-b.example"]) == []


def test_an_entry_until_today_still_applies(tmp_path):
    ctx, _ = _ctx(tmp_path, text=f'[[entries]]\naddress = "{OPTED}"\n'
                              f'until = "{TODAY.isoformat()}"\n')
    assert addrs(mail.check_recipients(ctx, [OPTED])) == [(OPTED, "", "exclude")]


def test_display_name_forms_are_matched_by_address(tmp_path):
    ctx, _ = _ctx(tmp_path)
    w = mail.check_recipients(ctx, [f"Colleague <{OPTED}>", f"  {OPTED}  "])
    assert len(w) == 2 and all(x.address.lower() == OPTED for x in w)


def test_a_per_call_file_overrides_the_profile(tmp_path):
    other = tmp_path / "project.toml"
    other.write_text(f'[[entries]]\naddress = "{OK}"\naction = "warn"\n')
    ctx, _ = _ctx(tmp_path)
    w = mail.check_recipients(ctx, [OPTED, OK], exclusions_file=str(other))
    assert addrs(w) == [(OK, "", "warn")]


def test_no_list_configured_means_no_matches(tmp_path):
    ctx, _ = _ctx(tmp_path, configured=False)
    assert mail.check_recipients(ctx, [OPTED]) == []


@pytest.mark.parametrize("text", [
    None,                                               # file missing
    "not = [valid",                                     # not TOML
    '[[entries]]\naction = "exclude"\n',                # no address
    f'[[entries]]\naddress = "{OPTED}"\naction = "block"\n',   # unknown action
    f'[[entries]]\naddress = "{OPTED}"\ncolour = "red"\n',     # unknown key
    f'[[entries]]\naddress = "{OPTED}"\nuntil = "soon"\n',     # bad date
    'entries = "nope"\n',                               # wrong shape
])
def test_a_configured_list_that_cannot_be_read_is_an_error(tmp_path, text):
    ctx, seen = _ctx(tmp_path, text=text)
    with pytest.raises(ValueError, match="exclusion"):
        mail.check_recipients(ctx, [OPTED])
    with pytest.raises(ValueError, match="exclusion"):
        mail.create_draft(ctx, to=[OK], subject="s", body_html="b")
    assert not seen                                     # nothing created


def test_the_profile_key_is_accepted_and_expands_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / "x.toml").write_text("")
    cfg = tmp_path / "profiles.toml"
    cfg.write_text('[profiles.tenant-a]\ntenant_id = "t1"\nclient_id = "c1"\n'
                   'exclusions_file = "~/x.toml"\n')
    p = load_profiles(cfg)["tenant-a"]
    assert p.exclusions_file == "~/x.toml"
    ctx = Ctx(profiles={"tenant-a": p})
    assert mail.check_recipients(ctx, [OPTED]) == []     # empty file: no entries


# --- draft tools warn and still create -------------------------------------

def test_create_draft_warns_and_keeps_every_recipient(tmp_path):
    ctx, seen = _ctx(tmp_path)
    d = mail.create_draft(ctx, to=[OPTED, OK], cc=[BOUNCE], subject="Agenda",
                          body_html="<p>hi</p>")
    assert isinstance(d, Draft) and isinstance(d, Message)
    assert sorted(r.address for r in d.to) == sorted([OPTED, OK])   # not removed
    assert addrs(d.recipient_warnings) == [(OPTED, "to", "exclude"),
                                           (BOUNCE, "cc", "warn")]
    assert ("POST", f"/v1.0/users/{MAILBOX}/messages") in seen


def test_bcc_is_checked_too(tmp_path):
    ctx, _ = _ctx(tmp_path)
    d = mail.create_draft(ctx, to=[OK], bcc=[OPTED], subject="s", body_html="b")
    assert addrs(d.recipient_warnings) == [(OPTED, "bcc", "exclude")]


def test_reply_all_flags_recipients_the_caller_never_named(tmp_path):
    ctx, _ = _ctx(tmp_path, draft=_graph_draft(to=[OK], cc=[OPTED],
                                               subject="RE: Agenda"))
    d = mail.create_reply_draft(ctx, "m1", "<p>thanks</p>", reply_all=True)
    assert addrs(d.recipient_warnings) == [(OPTED, "cc", "exclude")]


def test_forward_and_update_warn_too(tmp_path):
    ctx, _ = _ctx(tmp_path, draft=_graph_draft(to=[BOUNCE], subject="FW: Agenda"))
    f = mail.create_forward_draft(ctx, "m1", to=[BOUNCE])
    assert addrs(f.recipient_warnings) == [(BOUNCE, "to", "warn")]
    ctx, _ = _ctx(tmp_path, draft=_graph_draft(to=[OPTED], subject="Agenda"))
    u = mail.update_draft(ctx, "d1", to=[OPTED])
    assert addrs(u.recipient_warnings) == [(OPTED, "to", "exclude")]


def test_scope_uses_the_drafts_own_subject(tmp_path):
    ctx, _ = _ctx(tmp_path)
    who = ["agent@tenant-a.example"]
    hit = mail.create_draft(ctx, to=who, subject="Co-ordination Meeting notes",
                            body_html="b")
    miss = mail.create_draft(ctx, to=who, subject="Invoice", body_html="b")
    assert len(hit.recipient_warnings) == 1 and miss.recipient_warnings == []


def test_drafts_without_a_list_carry_an_empty_warning_list(tmp_path):
    ctx, _ = _ctx(tmp_path, configured=False)
    d = mail.create_draft(ctx, to=[OPTED], subject="s", body_html="b")
    assert d.recipient_warnings == []


def test_get_message_is_unchanged(tmp_path):
    ctx, _ = _ctx(tmp_path, draft=_graph_draft(to=[OPTED]))
    m = mail.get_message(ctx, "d1")
    assert not hasattr(m, "recipient_warnings") or m.recipient_warnings == []


# --- send refuses -----------------------------------------------------------

def test_send_refuses_an_excluded_recipient(tmp_path):
    ctx, seen = _ctx(tmp_path, send=True, draft=_graph_draft(to=[OK], bcc=[OPTED]))
    with pytest.raises(ValueError, match="exclu") as e:
        mail.send_draft(ctx, "d1")
    assert OPTED in str(e.value)
    assert not any(p.endswith("/send") for _, p in seen)


def test_send_override_sends_and_says_what_it_overrode(tmp_path):
    ctx, seen = _ctx(tmp_path, send=True, draft=_graph_draft(to=[OPTED, OK]),
                     allow_exclusion_override=True)
    r = mail.send_draft(ctx, "d1", override_exclusions=True)
    assert r["sent"] is True
    assert [w.address.lower() for w in r["recipient_warnings"]] == [OPTED]
    assert any(p.endswith("/send") for _, p in seen)


def test_warn_entries_never_block_a_send(tmp_path):
    ctx, seen = _ctx(tmp_path, send=True, draft=_graph_draft(to=[BOUNCE]))
    r = mail.send_draft(ctx, "d1")
    assert r["sent"] is True
    assert [w.action for w in r["recipient_warnings"]] == ["warn"]


def test_send_reads_the_subject_and_bcc_it_checks(tmp_path):
    ctx, _ = _ctx(tmp_path, send=True, draft=_graph_draft(
        to=["agent@tenant-a.example"], subject="Co-ordination Meeting"))
    with pytest.raises(ValueError, match="exclu"):
        mail.send_draft(ctx, "d1")


def test_send_without_a_list_is_unchanged(tmp_path):
    ctx, _ = _ctx(tmp_path, configured=False, send=True, draft=_graph_draft(to=[OPTED]))
    r = mail.send_draft(ctx, "d1")
    assert r["sent"] is True and r["recipient_warnings"] == []


# --- registration -----------------------------------------------------------

def test_check_recipients_is_read_tier():
    from ckm365 import tools
    assert mail.check_recipients in tools.READ["mail"]
    assert mail.check_recipients not in tools.WRITE["mail"]


def test_unknown_profile_keys_are_still_refused(tmp_path):
    cfg = tmp_path / "profiles.toml"
    cfg.write_text('[profiles.tenant-a]\ntenant_id = "t1"\nclient_id = "c1"\n'
                   'exclusion_file = "x"\n')                   # typo
    with pytest.raises(ConfigError):
        load_profiles(cfg)
