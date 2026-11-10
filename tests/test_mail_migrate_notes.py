"""Offline spec for 58x5p7: files the migration planner should stop
calling `manual`, because there is nothing about them to migrate.

A full manual review of one real correspondence folder after v2.10.1 left
33 items `manual`, every one correctly: guides, digests, meeting notes,
attachment conversions, chat records, an unsent draft, and `.msg` files
whose sidecar already carries the Message-ID. A rerun reports the same 33
forever and the next reviewer looks at them again. These rules take the
ones a machine can recognise out of that bucket:

- `note`: a NEW planner action, "not a mail record, nothing to migrate".
  A record with no front matter and no same-stem .eml/.msg; a hand-written
  front matter whose `type` is set and is not Email; an .eml carrying
  `X-Unsent` (a draft that was never sent has no Message-ID by nature).
  migrate_correspondence leaves notes out of its results, like `none`.
- `none` for a .msg whose same-stem record carries a Message-ID: the
  sidecar already identifies it, so the .msg needs no parser.

What stays `manual` (test_mail_migrate.py): a note that owns the `.md`
name a same-stem .eml would pair to, a .msg with no identified sidecar,
an .eml without a Message-ID that is not an unsent draft, a mail record
without an id.

Skipped as a module until the planner knows the `note` action.
"""

import tempfile
from pathlib import Path

import pytest

migrate = pytest.importorskip("ckm365.tools.mail.migrate")


def _knows_notes() -> bool:
    with tempfile.TemporaryDirectory() as d, pytest.MonkeyPatch.context() as env:
        # Collection runs before conftest's disk/state fixtures.
        env.setenv("CKM365_DOWNLOAD_ROOT", d)
        env.setenv("XDG_STATE_HOME", str(Path(d, "state")))
        Path(d, "n.md").write_text("# a note\n")
        items = migrate.plan_correspondence_migration(None, d)["items"]
        return items[0]["action"] == "note"


if not _knows_notes():
    pytest.skip("planner has no `note` action yet (58x5p7)",
                allow_module_level=True)

from test_mail_migrate import ID1, ID2, by_name, eml, hand, plan, v01, v02  # noqa: E402
from test_mail_migrate_apply import _ctx  # noqa: E402

MSG = b"\xd0\xcf\x11\xe0" + b"\0" * 64


def typed(type_, imid=None):
    """A hand-written front matter with a `type` that is not ours."""
    return ("---\n"
            f"type: {type_}\n"
            "title: Supplier register\n"
            + (f"internet_message_id: {imid}\n" if imid else "")
            + "---\n\nRows I keep by hand.\n")


def unsent(imid=None):
    head = "X-Unsent: 1\r\nSubject: draft\r\n"
    head += f"Message-ID: {imid}\r\n" if imid else ""
    return (head + "\r\nnot sent yet\r\n").encode()


# --- note: no front matter, no mail beside it ------------------------------

def test_a_file_with_no_front_matter_and_no_mail_beside_it_is_a_note(tmp_path):
    (tmp_path / "README.md").write_text("# How this folder works\n")
    (tmp_path / "digest.txt").write_text("Weekly digest, typed up.\n")
    items = by_name(plan(tmp_path))
    for name in ("README.md", "digest.txt"):
        assert items[name]["version"] == "none"
        assert items[name]["action"] == "note"
        assert items[name]["reason"]                  # says why: not mail
        assert items[name]["internet_message_id"] is None


def test_a_same_stem_msg_also_keeps_a_bare_file_manual(tmp_path):
    (tmp_path / "call.md").write_text("# what we said\n")
    (tmp_path / "call.msg").write_bytes(MSG)
    assert by_name(plan(tmp_path))["call.md"]["action"] == "manual"


def test_the_manual_reason_names_the_mail_file_that_owns_the_stem(tmp_path):
    (tmp_path / "q.md").write_text("# notes\n")
    (tmp_path / "q.eml").write_bytes(eml(ID1))
    item = by_name(plan(tmp_path))["q.md"]
    assert item["action"] == "manual" and "q.eml" in item["reason"]


# --- note: a front matter that is not about an email -----------------------

@pytest.mark.parametrize("type_", ["Meeting", "WhatsApp", '"Register"', "topic"])
def test_a_front_matter_whose_type_is_not_email_is_a_note(tmp_path, type_):
    (tmp_path / "reg.md").write_text(typed(type_))
    item = by_name(plan(tmp_path))["reg.md"]
    assert item["version"] == "hand-written"
    assert item["action"] == "note"
    assert type_.strip('"') in item["reason"]


@pytest.mark.parametrize("type_", ["Email", "email", '"EMAIL"'])
def test_type_email_in_any_case_is_still_mail(tmp_path, type_):
    (tmp_path / "m.md").write_text(typed(type_))
    assert by_name(plan(tmp_path))["m.md"]["action"] == "manual"   # no id


def test_no_type_at_all_is_still_treated_as_mail(tmp_path):
    (tmp_path / "notes.md").write_text(hand())                    # no `type`
    assert by_name(plan(tmp_path))["notes.md"]["action"] == "manual"


def test_our_own_records_are_unaffected_by_the_type_rule(tmp_path):
    (tmp_path / "cur.md").write_text(v02(ID1))
    (tmp_path / "old.md").write_text(v01(ID2))
    items = by_name(plan(tmp_path))
    assert items["cur.md"]["action"] == "none"
    assert items["old.md"]["action"] == "upgrade"


# --- note: an unsent draft .eml --------------------------------------------

def test_an_unsent_draft_eml_is_a_note_not_manual(tmp_path):
    (tmp_path / "draft.eml").write_bytes(unsent())
    item = by_name(plan(tmp_path))["draft.eml"]
    assert item["kind"] == "eml"
    assert item["action"] == "note"
    assert "X-Unsent" in item["reason"]


def test_an_unsent_draft_is_never_paired_even_with_a_message_id(tmp_path):
    (tmp_path / "draft.eml").write_bytes(unsent(ID1))
    assert by_name(plan(tmp_path))["draft.eml"]["action"] == "note"


def test_a_sent_eml_without_a_message_id_is_still_manual(tmp_path):
    (tmp_path / "odd.eml").write_bytes(eml(None))
    assert by_name(plan(tmp_path))["odd.eml"]["action"] == "manual"


def test_notes_never_take_part_in_duplicate_detection(tmp_path):
    (tmp_path / "a.eml").write_bytes(unsent(ID1))
    (tmp_path / "b.eml").write_bytes(eml(ID1))
    items = by_name(plan(tmp_path))
    assert items["a.eml"]["action"] == "note"
    assert items["b.eml"]["action"] == "pair"        # not a duplicate of a.eml
    assert items["b.eml"]["duplicate_of"] is None


# --- .msg with an identified sidecar ---------------------------------------

def test_a_msg_whose_sidecar_carries_an_id_is_current(tmp_path):
    (tmp_path / "call.msg").write_bytes(MSG)
    (tmp_path / "call.md").write_text(hand(ID1))
    items = by_name(plan(tmp_path))
    assert items["call.msg"]["action"] == "none"
    assert items["call.msg"]["pair"] == "call.md"
    assert items["call.msg"]["reason"] is None
    assert items["call.md"]["action"] == "none"


def test_a_msg_whose_sidecar_has_no_id_stays_manual(tmp_path):
    (tmp_path / "call.msg").write_bytes(MSG)
    (tmp_path / "call.md").write_text(hand())
    items = by_name(plan(tmp_path))
    assert items["call.msg"]["action"] == "manual"
    assert "dependency" in items["call.msg"]["reason"]


def test_a_msg_is_still_never_opened(tmp_path):
    # Unreadable bytes must not matter: the planner decides from the sidecar.
    (tmp_path / "call.msg").write_bytes(b"\xff" * 16)
    (tmp_path / "call.md").write_text(hand(ID1))
    item = by_name(plan(tmp_path))["call.msg"]
    assert item["action"] == "none" and item["internet_message_id"] is None


# --- the folder as a whole -------------------------------------------------

def test_counts_and_keys_include_notes(tmp_path):
    (tmp_path / "README.md").write_text("# folder guide\n")
    (tmp_path / "reg.md").write_text(typed("Register"))
    (tmp_path / "draft.eml").write_bytes(unsent())
    (tmp_path / "call.msg").write_bytes(MSG)
    (tmp_path / "call.md").write_text(hand(ID1))
    result = plan(tmp_path)
    assert result["counts"] == {"note": 3, "none": 2}
    assert sum(result["counts"].values()) == len(result["items"])
    keys = {"name", "kind", "version", "internet_message_id", "pair",
            "duplicate_of", "action", "reason"}
    assert all(set(i) == keys for i in result["items"])


def test_migrate_leaves_notes_out_of_its_results_and_alone(tmp_path):
    (tmp_path / "README.md").write_text("# folder guide\n")
    (tmp_path / "draft.eml").write_bytes(unsent())
    (tmp_path / "call.msg").write_bytes(MSG)
    (tmp_path / "call.md").write_text(hand(ID1))
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    ctx, seen = _ctx()
    result = migrate.migrate_correspondence(ctx, str(tmp_path), dry_run=False)
    assert result["results"] == [] and result["counts"] == {}
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == before
    assert not seen


def test_the_planner_docstring_teaches_the_thread_record_convention():
    doc = migrate.plan_correspondence_migration.__doc__
    assert "note" in doc
    assert "thread" in doc.lower() and "top level" in doc.lower()
