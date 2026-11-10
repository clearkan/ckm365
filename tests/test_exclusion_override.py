"""Offline spec for CKM-v0yzaw (v2.14.0): overriding the recipient
exclusion list is the OPERATOR's call, not the agent's.

send_draft refuses a draft with an `exclude` match unless
override_exclusions=True, and until now that flag was an ordinary tool
argument: a prompt-injected agent could bypass the list in the same call
that sends. Approved by seanwy on 10 Nov 2026.

Design:
- New profile key `allow_exclusion_override` (TOML boolean, default
  false; anything else is a ConfigError). It is in `_PROFILE_KEYS`.
- send_draft(override_exclusions=True) on a draft that HAS exclude
  matches sends only when the profile sets allow_exclusion_override =
  true. Otherwise it raises ValueError naming the key and the excluded
  addresses, and nothing is sent. (With no exclude match the flag has
  nothing to override and the send goes ahead as before.)
- Every override that actually lets an excluded recipient through is
  logged at WARNING with the mailbox, the message id and the COUNT of
  overridden recipients, never the addresses (the logging rule: ids and
  counts only).
- The tool's docstring says the override needs the profile key, so the
  calling agent learns it from the schema rather than from a refusal.

Skipped as a module until Profile has allow_exclusion_override.
"""

import json
import logging

import httpx
import pytest

from ckm365.config import ConfigError, Profile, load_profiles

if "allow_exclusion_override" not in Profile.__dataclass_fields__:
    pytest.skip("operator-only exclusion override not built yet (CKM-v0yzaw)",
                allow_module_level=True)

from ckm365.graph import Graph  # noqa: E402
from ckm365.tools import Ctx, mail  # noqa: E402

MAILBOX = "user@tenant-a.example"
OPTED = "opted-out@tenant-b.example"
OK = "fine@tenant-b.example"
LIST = f'[[entries]]\naddress = "{OPTED}"\ntype = "opt-out"\n'


class FakeAuth:
    def token(self):
        return "fake-token"

    def username(self):
        return MAILBOX


def _ctx(tmp_path, *, to=(OPTED, OK), **profile_kw):
    seen = []
    draft = {"id": "d1", "isDraft": True, "subject": "Weekly update",
             "toRecipients": [{"emailAddress": {"address": a}} for a in to],
             "ccRecipients": [], "bccRecipients": [],
             "body": {"contentType": "html", "content": "<p>x</p>"}}

    def handler(request):
        seen.append((request.method, request.url.path))
        if request.method == "POST" and request.url.path.endswith("/send"):
            return httpx.Response(202)
        return httpx.Response(200, json=draft)

    path = tmp_path / "exclusions.toml"
    path.write_text(LIST)
    ctx = Ctx(profiles={"tenant-a": Profile(
        name="tenant-a", tenant_id="t1", client_id="c1",
        default_mailbox=MAILBOX, exclusions_file=str(path), **profile_kw)},
        write_enabled=True, send_enabled=True)
    ctx.set_graph("tenant-a", Graph(FakeAuth(),
                                    transport=httpx.MockTransport(handler)))
    return ctx, seen


def _sent(seen):
    return any(m == "POST" and p.endswith("/send") for m, p in seen)


# --- the profile key ---------------------------------------------------------------

def test_defaults_to_off():
    assert Profile(name="p", tenant_id="t", client_id="c").allow_exclusion_override is False


@pytest.mark.parametrize("value", ["true", 1, "yes"])
def test_must_be_a_boolean(value):
    with pytest.raises(ConfigError, match="allow_exclusion_override"):
        Profile(name="p", tenant_id="t", client_id="c",
                allow_exclusion_override=value)


def test_accepted_in_profiles_toml(tmp_path):
    path = tmp_path / "profiles.toml"
    path.write_text('[profiles.p]\ntenant_id = "t"\nclient_id = "c"\n'
                    "allow_exclusion_override = true\n")
    assert load_profiles(path)["p"].allow_exclusion_override is True


# --- send_draft ------------------------------------------------------------------------

def test_agent_cannot_override_without_the_profile_key(tmp_path):
    ctx, seen = _ctx(tmp_path)
    with pytest.raises(ValueError, match="allow_exclusion_override") as e:
        mail.send_draft(ctx, "d1", override_exclusions=True)
    assert OPTED in str(e.value)
    assert not _sent(seen)


def test_profile_key_lets_the_override_through(tmp_path):
    ctx, seen = _ctx(tmp_path, allow_exclusion_override=True)
    result = mail.send_draft(ctx, "d1", override_exclusions=True)
    assert result["sent"] is True and _sent(seen)


def test_profile_key_alone_does_not_override(tmp_path):
    ctx, seen = _ctx(tmp_path, allow_exclusion_override=True)
    with pytest.raises(ValueError, match="exclusion list"):
        mail.send_draft(ctx, "d1")
    assert not _sent(seen)


def test_flag_with_nothing_to_override_still_sends(tmp_path):
    ctx, seen = _ctx(tmp_path, to=(OK,))
    assert mail.send_draft(ctx, "d1", override_exclusions=True)["sent"] is True


def test_override_is_logged_at_warning_without_addresses(tmp_path, caplog):
    ctx, _ = _ctx(tmp_path, allow_exclusion_override=True)
    with caplog.at_level(logging.INFO, logger="ckm365"):
        mail.send_draft(ctx, "d1", override_exclusions=True)
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    text = warnings[0].getMessage()
    assert "override" in text.lower() and "d1" in text and "1" in text
    assert OPTED not in caplog.text


def test_docstring_names_the_profile_key():
    assert "allow_exclusion_override" in mail.send_draft.__doc__
