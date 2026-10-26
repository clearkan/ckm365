"""Offline tests for the correspondence migration planner (mr31re).

plan_correspondence_migration is LOCAL ONLY: it classifies the files in
one correspondence folder and proposes an action per file, and it never
writes, never calls Graph and never recurses. These tests build folders
from the record shapes that exist in the wild — OKF v0.2 (current), OKF
v0.1 (`timestamp`/`exported_by`), hand-written sidecars, raw .eml, and
.msg — and assert the plan says the right thing about each, says it the
same way twice, and leaves the folder untouched.
"""

import pytest

migrate = pytest.importorskip("ckm365.tools.mail.migrate")
from ckm365.tools import mail  # noqa: E402

ID1 = "<one@tenant-a.example>"
ID2 = "<two@tenant-b.example>"
ID3 = "<three@tenant-a.example>"


def v02(imid=ID1, title="Q1 figures"):
    """What export_message writes today (OKF v0.2)."""
    return ("---\n"
            'type: "Email"\n'
            f'title: "{title}"\n'
            'description: "Please see the attached"\n'
            'resource: "https://outlook.example/x"\n'
            'tags: ["email", "inbound"]\n'
            'generated: {by: "ckm365/2.9.0", at: "2026-10-01T01:02:03Z"}\n'
            'from: "Alex <other-user@tenant-b.example>"\n'
            'to: "operator@tenant-a.example"\n'
            'cc: ""\n'
            'mailbox: "operator@tenant-a.example"\n'
            'message_id: "AAMkAG1"\n'
            + (f'internet_message_id: "{imid}"\n' if imid else "")
            + "has_attachments: false\n"
            "---\n\n# Q1 figures\n\nPlease see the attached.\n")


def v01(imid=ID1):
    """What v2.5.0-v2.7.0 wrote (OKF v0.1): timestamp + exported_by."""
    return ("---\n"
            'type: "Email"\n'
            'title: "Q1 figures"\n'
            'resource: "https://outlook.example/x"\n'
            'timestamp: "2026-10-01T01:02:03Z"\n'
            'exported_by: "ckm365/2.5.0"\n'
            'mailbox: "operator@tenant-a.example"\n'
            'message_id: "AAMkAG1"\n'
            f'internet_message_id: "{imid}"\n'
            "---\n\n# Q1 figures\n\nbody\n")


def hand(imid=None):
    """A sidecar a person wrote from a .msg: front matter, their own keys."""
    return ("---\n"
            "subject: Q1 figures\n"
            "from: Alex\n"
            "date: 2026-10-01\n"
            + (f"internet_message_id: {imid.strip('<>')}\n" if imid else "")
            + "---\n\nNotes I typed myself.\n")


def eml(imid=ID1):
    head = (f"Message-ID: {imid}\r\n" if imid else "") + "Subject: Q1\r\n"
    return (head + "\r\nbody\r\n").encode()


def plan(folder):
    return migrate.plan_correspondence_migration(None, str(folder))


def by_name(result):
    return {i["name"]: i for i in result["items"]}


# --- classification ---------------------------------------------------------

def test_current_record_needs_nothing(tmp_path):
    (tmp_path / "q1.md").write_text(v02())
    item = by_name(plan(tmp_path))["q1.md"]
    assert item["kind"] == "record"
    assert item["version"] == "okf-0.2"
    assert item["internet_message_id"] == ID1
    assert item["action"] == "none"


def test_v01_record_is_an_upgrade(tmp_path):
    (tmp_path / "q1.md").write_text(v01())
    item = by_name(plan(tmp_path))["q1.md"]
    assert item["version"] == "okf-0.1"
    assert item["internet_message_id"] == ID1
    assert item["action"] == "upgrade"


def test_hand_written_with_an_id_is_left_alone(tmp_path):
    (tmp_path / "notes.txt").write_text(hand(ID1))
    item = by_name(plan(tmp_path))["notes.txt"]
    assert item["version"] == "hand-written"
    assert item["internet_message_id"] == "one@tenant-a.example"
    assert item["action"] == "none"


def test_hand_written_without_an_id_backfills_from_its_eml(tmp_path):
    (tmp_path / "notes.md").write_text(hand())
    (tmp_path / "notes.eml").write_bytes(eml(ID1))
    items = by_name(plan(tmp_path))
    rec, raw = items["notes.md"], items["notes.eml"]
    assert rec["action"] == "backfill-id"
    assert rec["pair"] == "notes.eml"
    assert rec["internet_message_id"] == ID1   # the id it WOULD get
    assert raw["action"] == "none"
    assert raw["pair"] == "notes.md"


def test_hand_written_without_an_id_and_no_eml_is_manual(tmp_path):
    (tmp_path / "notes.md").write_text(hand())
    item = by_name(plan(tmp_path))["notes.md"]
    assert item["action"] == "manual"
    assert "Message-ID" in item["reason"]


def test_no_front_matter_is_manual(tmp_path):
    (tmp_path / "loose.md").write_text("# Just a note\n\nno front matter\n")
    item = by_name(plan(tmp_path))["loose.md"]
    assert item["version"] == "none"
    assert item["action"] == "manual"


def test_eml_without_a_record_wants_pairing(tmp_path):
    (tmp_path / "evidence.eml").write_bytes(eml(ID1))
    item = by_name(plan(tmp_path))["evidence.eml"]
    assert item["kind"] == "eml"
    assert item["version"] is None
    assert item["internet_message_id"] == ID1
    assert item["action"] == "pair"


def test_eml_and_record_pair_by_message_id_not_by_name(tmp_path):
    (tmp_path / "2026-10-01-q1.md").write_text(v02(ID1))
    (tmp_path / "evidence.eml").write_bytes(eml(ID1))
    items = by_name(plan(tmp_path))
    assert items["evidence.eml"]["action"] == "none"
    assert items["evidence.eml"]["pair"] == "2026-10-01-q1.md"
    assert items["2026-10-01-q1.md"]["pair"] == "evidence.eml"


def test_eml_without_a_message_id_is_manual(tmp_path):
    (tmp_path / "odd.eml").write_bytes(eml(None))
    item = by_name(plan(tmp_path))["odd.eml"]
    assert item["internet_message_id"] is None
    assert item["action"] == "manual"


def test_msg_is_reported_not_opened(tmp_path):
    (tmp_path / "old.msg").write_bytes(b"\xd0\xcf\x11\xe0" + b"\0" * 64)
    item = by_name(plan(tmp_path))["old.msg"]
    assert item["kind"] == "msg"
    assert item["action"] == "manual"
    assert "dependency" in item["reason"]


def test_brackets_are_optional_when_matching_ids(tmp_path):
    (tmp_path / "notes.txt").write_text(hand(ID1))        # written without <>
    (tmp_path / "raw.eml").write_bytes(eml(ID1))          # header keeps them
    items = by_name(plan(tmp_path))
    assert items["notes.txt"]["pair"] == "raw.eml"
    assert items["raw.eml"]["action"] == "none"


# --- duplicates -------------------------------------------------------------

def test_second_record_with_the_same_id_is_flagged_first_wins(tmp_path):
    (tmp_path / "a-first.md").write_text(v02(ID1))
    (tmp_path / "b-second.md").write_text(v02(ID1))
    items = by_name(plan(tmp_path))
    assert items["a-first.md"]["action"] == "none"
    assert items["a-first.md"]["duplicate_of"] is None
    assert items["b-second.md"]["action"] == "flag-duplicate"
    assert items["b-second.md"]["duplicate_of"] == "a-first.md"


def test_two_emls_with_the_same_id_are_duplicates_too(tmp_path):
    (tmp_path / "x.eml").write_bytes(eml(ID2))
    (tmp_path / "y.eml").write_bytes(eml(ID2))
    items = by_name(plan(tmp_path))
    assert items["x.eml"]["action"] == "pair"
    assert items["y.eml"]["action"] == "flag-duplicate"
    assert items["y.eml"]["duplicate_of"] == "x.eml"


def test_a_record_and_its_eml_are_a_pair_not_a_duplicate(tmp_path):
    (tmp_path / "q.md").write_text(v02(ID1))
    (tmp_path / "q.eml").write_bytes(eml(ID1))
    items = by_name(plan(tmp_path))
    assert {i["action"] for i in items.values()} == {"none"}


# --- the folder as a whole --------------------------------------------------

def test_other_files_and_subfolders_are_counted_not_classified(tmp_path):
    (tmp_path / "q1.md").write_text(v02())
    (tmp_path / "deck.pdf").write_bytes(b"%PDF")
    (tmp_path / "shot.png").write_bytes(b"\x89PNG")
    (tmp_path / "half.md.part").write_text("")
    (tmp_path / "2025").mkdir()
    (tmp_path / "2025" / "old.md").write_text(v01(ID3))   # NOT recursed into
    result = plan(tmp_path)
    assert [i["name"] for i in result["items"]] == ["q1.md"]
    assert result["skipped"] == {".pdf": 1, ".png": 1, ".part": 1}
    assert result["subfolders"] == ["2025"]


def test_items_are_sorted_and_counts_add_up(tmp_path):
    (tmp_path / "c.md").write_text(v02(ID1))
    (tmp_path / "a.md").write_text(v01(ID2))
    (tmp_path / "b.eml").write_bytes(eml(ID3))
    (tmp_path / "d.msg").write_bytes(b"\0" * 8)
    result = plan(tmp_path)
    assert [i["name"] for i in result["items"]] == ["a.md", "b.eml", "c.md", "d.msg"]
    assert result["counts"] == {"upgrade": 1, "pair": 1, "none": 1, "manual": 1}
    assert sum(result["counts"].values()) == len(result["items"])
    assert result["dir"] == str(tmp_path.resolve())


def test_every_item_carries_the_same_keys(tmp_path):
    (tmp_path / "q.md").write_text(v02())
    (tmp_path / "q.eml").write_bytes(eml())
    (tmp_path / "old.msg").write_bytes(b"\0" * 8)
    keys = {"name", "kind", "version", "internet_message_id", "pair",
            "duplicate_of", "action", "reason"}
    for item in plan(tmp_path)["items"]:
        assert set(item) == keys, item["name"]


def test_plan_is_read_only_and_repeatable(tmp_path):
    files = {"a.md": v02(ID1).encode(), "b.md": v01(ID2).encode(),
             "c.md": hand().encode(), "c.eml": eml(ID3), "x.msg": b"\0" * 8}
    for name, data in files.items():
        (tmp_path / name).write_bytes(data)
    before = {p.name: (p.stat().st_mtime_ns, p.read_bytes())
              for p in tmp_path.iterdir()}
    first = plan(tmp_path)
    second = plan(tmp_path)
    assert first == second
    after = {p.name: (p.stat().st_mtime_ns, p.read_bytes())
             for p in tmp_path.iterdir()}
    assert after == before


def test_unreadable_file_is_manual_not_a_crash(tmp_path):
    (tmp_path / "ok.md").write_text(v02())
    bad = tmp_path / "bad.md"
    bad.write_text(v02(ID2))
    bad.chmod(0)
    try:
        items = by_name(plan(tmp_path))
        assert items["ok.md"]["action"] == "none"
        assert items["bad.md"]["action"] == "manual"
    finally:
        bad.chmod(0o644)


# --- fences and errors ------------------------------------------------------

def test_dir_must_exist_and_be_a_directory(tmp_path):
    with pytest.raises(ValueError, match="not a directory"):
        plan(tmp_path / "missing")
    (tmp_path / "file.md").write_text(v02())
    with pytest.raises(ValueError, match="not a directory"):
        plan(tmp_path / "file.md")


def test_dir_is_fenced_by_the_download_root(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    monkeypatch.setenv("CKM365_DOWNLOAD_ROOT", str(root))
    (root / "q.md").write_text(v02())
    assert plan(root)["counts"] == {"none": 1}
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    with pytest.raises(ValueError, match="outside the download root"):
        plan(outside)


# --- registration -----------------------------------------------------------

def test_registered_as_a_read_tier_mail_tool():
    from ckm365 import tools
    assert mail.plan_correspondence_migration is migrate.plan_correspondence_migration
    assert migrate.plan_correspondence_migration in tools.READ["mail"]
    assert migrate.plan_correspondence_migration not in tools.WRITE["mail"]
