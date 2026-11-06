"""Offline spec for unattended audits (2tcqc0 parts 1 and 2): severity
exit codes, a CI threshold, and a baseline of accepted findings.

Part 3 of the issue (read-only credentials for unattended runs) touches
tenants and is not here.

1. EXIT CODES BY SEVERITY: 0 clean, 1 WARN, 2 FAIL, 3 RISK; the highest
   level present wins. FAIL stays distinct from clean: an audit that
   could not read something is not a clean audit. `--fail-on
   {warn,fail,risk}` sets the threshold, default `risk`: below the
   threshold the exit is 0, at or above it the exit is the highest
   level's code. So by default only RISK fails a run, as before, but now
   with code 3 rather than 1.
2. BASELINE: `--baseline FILE` lists accepted findings, one per line, as
   `LEVEL<two spaces>text` exactly as the text report prints them
   (first line of the finding only); blank lines and `#` comments are
   ignored. A WARN or RISK row matching a line is still reported, marked
   `(baselined)`, but no longer raises the exit code. FAIL is never
   baselined: not seeing is not a known state. `--write-baseline FILE`
   writes the current run's WARN and RISK rows in that format (sorted,
   with a header comment), so the first nightly run can accept today's
   state. The file names real accounts, so it lives outside this repo.
3. The summary line counts baselined rows separately.

Skipped as a module until audit.exit_code exists.
"""

import pytest

from ckm365 import audit

if not hasattr(audit, "exit_code"):
    pytest.skip("audit CI mode not built yet (2tcqc0)", allow_module_level=True)

from ckm365.audit import Section  # noqa: E402
from ckm365.server import main  # noqa: E402

TENANT_A = "00000000-0000-0000-0000-00000000000a"


def sections(*rows):
    s = Section("Exchange Online (pwsh)", scope="tenant")
    for level, text in rows:
        s.add(level, text)
    return [s]


# --- exit codes ---------------------------------------------------------------

@pytest.mark.parametrize("rows,code", [
    ([], 0),
    ([("OK", "fine"), ("INFO", "note"), ("SKIP", "absent")], 0),
    ([("WARN", "w")], 1),
    ([("WARN", "w"), ("FAIL", "f")], 2),
    ([("FAIL", "f"), ("RISK", "r"), ("WARN", "w")], 3),
])
def test_highest_level_wins_at_the_lowest_threshold(rows, code):
    assert audit.exit_code(sections(*rows), fail_on="warn") == code


@pytest.mark.parametrize("fail_on,rows,code", [
    ("risk", [("WARN", "w"), ("FAIL", "f")], 0),       # the default: RISK only
    ("risk", [("RISK", "r")], 3),
    ("fail", [("WARN", "w")], 0),
    ("fail", [("FAIL", "f")], 2),
    ("fail", [("FAIL", "f"), ("RISK", "r")], 3),
    ("warn", [("WARN", "w")], 1),
])
def test_threshold(fail_on, rows, code):
    assert audit.exit_code(sections(*rows), fail_on=fail_on) == code


def test_default_threshold_is_risk():
    assert audit.exit_code(sections(("FAIL", "f"))) == 0
    assert audit.exit_code(sections(("RISK", "r"))) == 3


# --- baseline -----------------------------------------------------------------

BASELINE = """# accepted 2026-11-07
RISK  app Mailer holds Exchange role ApplicationImpersonation

WARN  ops@tenant-a.example: FullAccess for user@tenant-a.example
FAIL  could not sweep FullAccess grants
"""


def test_load_baseline_ignores_comments_and_blanks(tmp_path):
    path = tmp_path / "baseline.txt"
    path.write_text(BASELINE)
    assert audit.load_baseline(str(path)) == {
        ("RISK", "app Mailer holds Exchange role ApplicationImpersonation"),
        ("WARN", "ops@tenant-a.example: FullAccess for user@tenant-a.example"),
        ("FAIL", "could not sweep FullAccess grants"),
    }


def test_unreadable_baseline_is_an_error(tmp_path):
    with pytest.raises(ValueError, match="baseline"):
        audit.load_baseline(str(tmp_path / "missing.txt"))


def test_baselined_rows_do_not_raise_the_exit(tmp_path):
    path = tmp_path / "baseline.txt"
    path.write_text(BASELINE)
    s = sections(("RISK", "app Mailer holds Exchange role ApplicationImpersonation"),
                 ("WARN", "ops@tenant-a.example: FullAccess for user@tenant-a.example"))
    audit.apply_baseline(s, audit.load_baseline(str(path)))
    assert audit.exit_code(s, fail_on="warn") == 0


def test_a_new_finding_still_fails(tmp_path):
    path = tmp_path / "baseline.txt"
    path.write_text(BASELINE)
    s = sections(("RISK", "app Mailer holds Exchange role ApplicationImpersonation"),
                 ("RISK", "app NewThing holds Exchange role ApplicationImpersonation"))
    audit.apply_baseline(s, audit.load_baseline(str(path)))
    assert audit.exit_code(s) == 3


def test_fail_is_never_baselined(tmp_path):
    path = tmp_path / "baseline.txt"
    path.write_text(BASELINE)
    s = sections(("FAIL", "could not sweep FullAccess grants"))
    audit.apply_baseline(s, audit.load_baseline(str(path)))
    assert audit.exit_code(s, fail_on="fail") == 2


def test_level_must_match_too(tmp_path):
    path = tmp_path / "baseline.txt"
    path.write_text("WARN  something\n")
    s = sections(("RISK", "something"))
    audit.apply_baseline(s, audit.load_baseline(str(path)))
    assert audit.exit_code(s) == 3


def test_multiline_findings_match_on_their_first_line(tmp_path):
    path = tmp_path / "baseline.txt"
    path.write_text("WARN  explicit grants\n")
    s = sections(("WARN", "explicit grants\n  a@tenant-a.example\n  b@tenant-a.example"))
    audit.apply_baseline(s, audit.load_baseline(str(path)))
    assert audit.exit_code(s, fail_on="warn") == 0


def test_baselined_rows_are_still_reported_and_counted_apart(tmp_path):
    path = tmp_path / "baseline.txt"
    path.write_text("RISK  known\n")
    s = sections(("RISK", "known"), ("RISK", "new"))
    audit.apply_baseline(s, audit.load_baseline(str(path)))
    text = audit.render_text(s)
    assert "known (baselined)" in text and "new" in text
    assert "1 RISK" in text and "1 baselined" in text
    assert "(baselined)" in audit.render_md(s)


def test_write_baseline_round_trips(tmp_path):
    s = sections(("RISK", "r2"), ("INFO", "i"), ("WARN", "w\n  detail"),
                 ("FAIL", "f"), ("RISK", "r1"))
    path = tmp_path / "b.txt"
    audit.write_baseline(str(path), s)
    body = [ln for ln in path.read_text().splitlines()
            if ln and not ln.startswith("#")]
    assert body == ["RISK  r1", "RISK  r2", "WARN  w"]   # no INFO, no FAIL
    assert path.read_text().startswith("#")
    audit.apply_baseline(s, audit.load_baseline(str(path)))
    assert audit.exit_code(s, fail_on="warn") == 2       # only the FAIL is left


# --- the CLI ------------------------------------------------------------------

@pytest.fixture(autouse=True)
def no_processes(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError(f"tried to spawn a process: {args}")
    monkeypatch.setattr(audit.subprocess, "run", boom)


@pytest.fixture
def offline(tmp_path, monkeypatch):
    """No az, no pwsh, no login: the run yields one FAIL and some SKIPs."""
    monkeypatch.setattr(audit.shutil, "which", lambda _: None)
    monkeypatch.setattr("ckm365.auth.state_dir", lambda: tmp_path)
    path = tmp_path / "profiles.toml"
    path.write_text(f'[profiles.tenant-a]\ntenant_id = "{TENANT_A}"\n'
                    'client_id = "app-a"\n')
    path.chmod(0o600)
    return path


def cli(*argv):
    with pytest.raises(SystemExit) as exc:
        main(list(argv))
    return exc.value.code


def test_cli_fail_on(offline):
    assert cli("--profiles", str(offline), "audit") == 0
    assert cli("--profiles", str(offline), "audit", "--fail-on", "fail") == 2
    assert cli("--profiles", str(offline), "audit", "--fail-on", "warn") == 2


def test_cli_write_baseline_then_use_it(offline, tmp_path, capsys):
    base = tmp_path / "base.txt"
    cli("--profiles", str(offline), "audit", "--write-baseline", str(base))
    assert base.exists()
    assert cli("--profiles", str(offline), "audit", "--baseline", str(base),
               "--fail-on", "fail") == 2          # the FAIL is not baselined


def test_cli_missing_baseline_is_an_error(offline, tmp_path):
    code = cli("--profiles", str(offline), "audit",
               "--baseline", str(tmp_path / "nope.txt"))
    assert code not in (0, None) and "baseline" in str(code)
