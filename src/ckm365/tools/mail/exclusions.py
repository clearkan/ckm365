"""Local recipient exclusions: draft warnings and the send guard."""

import tomllib
from datetime import date
from email.utils import parseaddr
from pathlib import Path

from ...models import RecipientWarning
from ..context import Ctx


def load(path: str) -> list[dict]:
    """Load and validate an exclusion list, failing closed on bad files."""
    try:
        with Path(path).expanduser().open("rb") as stream:
            data = tomllib.load(stream)
        if data.keys() - {"entries"}:
            raise ValueError("unknown top-level key")
        entries = data.get("entries", [])
        if not isinstance(entries, list):
            raise ValueError("entries must be a list of tables")
        strings = {"address", "action", "type", "scope", "source", "notes"}
        for entry in entries:
            if not isinstance(entry, dict) or entry.keys() - strings - {"since", "until"}:
                raise ValueError("invalid entry keys")
            if not isinstance(entry.get("address"), str) or not entry["address"].strip():
                raise ValueError("address must be a non-empty string")
            for key in strings & entry.keys():
                if not isinstance(entry[key], str):
                    raise ValueError("entry fields must be strings")
            if entry.get("action", "exclude") not in {"exclude", "warn"}:
                raise ValueError("invalid action")
            for key in {"since", "until"} & entry.keys():
                if not isinstance(entry[key], str):
                    raise ValueError("dates must be ISO date strings")
                entry[key] = date.fromisoformat(entry[key])
        return entries
    except (OSError, ValueError, TypeError) as exc:
        raise ValueError(f"invalid exclusion list {path!r}: {exc}") from exc


def _normalise(address: str) -> str:
    return parseaddr(address)[1].strip().lower()


def check(entries, recipients: list[tuple[str, str]], subject: str | None
          ) -> list[RecipientWarning]:
    """Return every matching entry in recipient order."""
    warnings = []
    today = date.today()
    for address, field in recipients:
        address = _normalise(address)
        for entry in entries:
            if entry.get("until") is not None and entry["until"] < today:
                continue
            if "scope" in entry and (subject is None or
                                     entry["scope"].lower() not in subject.lower()):
                continue
            if address == _normalise(entry["address"]):
                warnings.append(RecipientWarning(
                    address=address, field=field,
                    action=entry.get("action", "exclude"),
                    type=entry.get("type", ""), source=entry.get("source", "")))
    return warnings


def for_profile(ctx, account) -> list[dict] | None:
    """Load the profile's list, or None when exclusions are disabled."""
    path = ctx.profile(account).exclusions_file
    return load(path) if path is not None else None


def draft_warnings(entries, draft) -> list[RecipientWarning]:
    """Check all recipient fields against the draft's own subject."""
    return check(entries or [], [(r.address, field) for field in ("to", "cc", "bcc")
                                for r in getattr(draft, field)], draft.subject)


def check_recipients(ctx: Ctx, addresses: list[str], *, subject: str | None = None,
                     exclusions_file: str | None = None,
                     account: str | None = None) -> list[RecipientWarning]:
    """Test a recipient list before building a draft; makes no Graph requests.

    TOML format:
    [[entries]] with required address = "colleague@tenant-b.example".
    action = "exclude" (default) or "warn"; optional type and source strings.
    Optional scope is a case-insensitive subject substring; notes is free text.
    Optional since/until are ISO date strings; entries expire after until.

    exclusions_file replaces the profile's list for this call. Draft tools
    warn; send refuses exclude matches unless explicitly overridden.
    """
    entries = (load(exclusions_file) if exclusions_file is not None
               else for_profile(ctx, account))
    return check(entries or [], [(address, "") for address in addresses], subject)
