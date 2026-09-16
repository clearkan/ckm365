#!/usr/bin/env python3
"""Refuse to let real identifiers reach this PUBLIC repo.

CLAUDE.md forbids committing real addresses, tenant names, client/project
names, GUIDs and infrastructure identifiers. That rule was breached twice in
one day by an agent that had just written it down, which is why this exists:
a rule you must remember is weaker than a check that runs.

    uv run python scripts/check-identifiers.py            # tracked files
    uv run python scripts/check-identifiers.py --staged   # staged content
    uv run python scripts/check-identifiers.py --rev-range origin/main..HEAD
                                                          # commit MESSAGES too

Heuristic by necessity — it cannot know your tenant's name. It catches the
SHAPES that have actually leaked here: real e-mail domains, host-like names
(an infrastructure word such as srv/work/node/box followed by one to three
digits) and absolute home paths. Exit 1 on any hit.

This file does NOT exempt itself, deliberately. The first version did — it
had to hold pattern strings — and it promptly smuggled two real hostnames
into its own docstring as examples, which is the exact failure it exists to
stop. Keep the examples fictional and it checks itself like everything else.
"""
import argparse
import re
import subprocess
import sys

# Public/vendor domains that legitimately appear in docs and code.
DOMAIN_OK = {
    "example.com", "example.org", "example.net", "tenant-a.example",
    "tenant-b.example", "their.host", "x.com", "microsoft.com",
    "graph.microsoft.com", "learn.microsoft.com", "login.microsoftonline.com",
    "outlook.office365.com", "office365.com", "github.com",
    "raw.githubusercontent.com", "keepachangelog.com", "oif.md",
    "openknowledgeformat.com", "openknowledge.ai", "python.org", "pypi.org",
    "astral.sh", "schema.org", "json-schema.org", "atlassian.net",
    "developer.microsoft.com", "onmicrosoft.com", "botframework.com",
    "files.pythonhosted.org", "pythonhosted.org",
    # The documented placeholders only. NOT *.onmicrosoft.com in general —
    # a real tenant leak looks exactly like a subdomain of it, so allowing
    # the parent would blind the check to the likeliest mistake.
    "tenant-a.onmicrosoft.com", "tenant-b.onmicrosoft.com",
}
# Technical tokens that look host-shaped but are not.
TOKEN_OK = {
    "sha256", "sha1", "base64", "base32", "rfc5322", "rfc2392", "iso8601",
    "utf8", "utf16", "md5", "crc32", "http2", "oauth2", "ipv4", "ipv6",
    "x509", "pkcs12", "p256", "v1", "v2",
}

EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})")
DOMAIN = re.compile(r"\b(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+"
                    r"(?:com|io|net|org|co|ai|dev|cloud|app)\b")
# A machine name: letters then digits, or an infra keyword plus digits.
HOSTISH = re.compile(r"\b[a-z][a-z-]{2,}(?:srv|work|host|node|box|vm|fw|gw|"
                     r"prod|stage|dev)[0-9]{1,3}\b")
HOMEPATH = re.compile(r"/home/[a-z][a-z0-9_-]*")


def hits(text: str, where: str) -> list[str]:
    out = []
    for m in EMAIL.finditer(text):
        dom = m.group(1).lower()
        if dom not in DOMAIN_OK and not dom.endswith(".example"):
            out.append(f"{where}: e-mail domain {dom!r} in {m.group(0)!r}")
    for m in DOMAIN.finditer(text):
        dom = m.group(0).lower()
        if dom not in DOMAIN_OK and not dom.endswith(".example") \
                and dom.split(".")[0] not in TOKEN_OK:
            out.append(f"{where}: domain-like {dom!r}")
    for m in HOSTISH.finditer(text):
        if m.group(0).lower() not in TOKEN_OK:
            out.append(f"{where}: host-like name {m.group(0)!r}")
    for m in HOMEPATH.finditer(text):
        out.append(f"{where}: absolute home path {m.group(0)!r}")
    return out


def run(cmd: list[str]) -> str:
    return subprocess.run(cmd, capture_output=True, text=True).stdout


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--staged", action="store_true")
    ap.add_argument("--rev-range")
    args = ap.parse_args()

    found: list[str] = []
    if args.rev_range:
        for sha in run(["git", "rev-list", args.rev_range]).split():
            msg = run(["git", "log", "-1", "--format=%B", sha])
            found += hits(msg, f"commit {sha[:8]} MESSAGE")
    if args.staged:
        found += hits(run(["git", "diff", "--cached"]), "staged diff")
    else:
        for path in run(["git", "ls-files"]).splitlines():
            if (path.startswith("tests/")        # fixtures are deliberate
                    or path == "uv.lock"):         # machine-generated, public
                continue
            try:
                with open(path, encoding="utf-8") as fh:
                    for n, line in enumerate(fh, 1):
                        found += hits(line, f"{path}:{n}")
            except (UnicodeDecodeError, OSError):
                continue

    for f in found:
        print(f)
    if found:
        print(f"\n{len(found)} possible identifier(s). CLAUDE.md forbids real "
              "addresses, tenant/client names, GUIDs and infrastructure names "
              "in this PUBLIC repo — including in COMMIT MESSAGES.")
        return 1
    print("no identifiers found")
    return 0


if __name__ == "__main__":
    sys.exit(main())
