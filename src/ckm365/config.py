"""Account profiles: one per (tenant, app registration), loaded from TOML.

Secrets never live in the profiles file — client-credential material comes
from env vars named after the profile (see Profile.client_credential).
"""

import os
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

_FORBIDDEN_TENANTS = {"common", "organizations", "consumers"}
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_PROFILE_KEYS = {"tenant_id", "client_id", "auth", "default_mailbox",
                 "description", "allow_send", "timezone", "signature_html"}
_TZ_RE = re.compile(r"[A-Za-z0-9_+/ -]{1,64}")
_MAX_SIGNATURE = 8192  # real HTML signatures measure a few hundred bytes
AUTH_MODES = ("device_code", "client_credential")


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Profile:
    name: str
    tenant_id: str  # pinned tenant GUID or verified domain — never an alias
    client_id: str
    auth: str = "device_code"
    default_mailbox: str | None = None
    description: str = ""  # optional, surfaced to agents via list_accounts
    allow_send: bool = True  # false hard-caps the send tier for this profile,
                             # regardless of server flags (defense in depth)
    signature_html: str | None = None  # this mailbox's sign-off, as an HTML
                                 # fragment, applied at DRAFT CREATION and
                                 # preserved by revise_draft (CKM-42). Local
                                 # by design: Outlook's roaming signature
                                 # would need MailboxSettings.Read, a scope
                                 # this app deliberately never asks for.
    timezone: str | None = None  # this mailbox's zone (IANA or the Windows
                                 # name Graph also accepts). Used where a
                                 # bare date would otherwise be guessed —
                                 # mail.flag due dates (CKM-34). Reading it
                                 # from Graph would need MailboxSettings.Read,
                                 # a scope this app deliberately never asks
                                 # for, so it is configured, not discovered.

    def __post_init__(self) -> None:
        if not _NAME_RE.fullmatch(self.name):
            raise ConfigError(f"profile name {self.name!r} must be [a-z0-9_-]")
        if not self.tenant_id or self.tenant_id.lower() in _FORBIDDEN_TENANTS:
            raise ConfigError(
                f"profile {self.name!r}: tenant_id must be a specific tenant, "
                f"never {'/'.join(sorted(_FORBIDDEN_TENANTS))}"
            )
        if not self.client_id:
            raise ConfigError(f"profile {self.name!r}: client_id is required")
        if self.auth not in AUTH_MODES:
            raise ConfigError(f"profile {self.name!r}: auth must be one of {AUTH_MODES}")
        if self.auth == "client_credential" and not self.default_mailbox:
            raise ConfigError(
                f"profile {self.name!r}: client_credential mode requires default_mailbox"
            )
        if not isinstance(self.allow_send, bool):
            # a string like "false" is truthy — the cap must never fail open
            raise ConfigError(
                f"profile {self.name!r}: allow_send must be a TOML boolean"
            )
        if self.signature_html is not None:
            # a non-string here would be spliced into an outgoing mail body
            if not isinstance(self.signature_html, str):
                raise ConfigError(
                    f"profile {self.name!r}: signature_html must be a TOML "
                    "string — a TOML multi-line literal (triple single "
                    "quotes) holds real HTML unescaped")
            if len(self.signature_html) > _MAX_SIGNATURE:
                raise ConfigError(
                    f"profile {self.name!r}: signature_html is "
                    f"{len(self.signature_html)} chars, over the "
                    f"{_MAX_SIGNATURE} cap — a signature is a sign-off, not a "
                    "document")
        if self.timezone is not None and not _TZ_RE.fullmatch(self.timezone):
            raise ConfigError(
                f"profile {self.name!r}: timezone must be a zone name like "
                "'Europe/London' or 'GMT Standard Time'"
            )

    def _env(self, key: str) -> str:
        return f"CKM365_{self.name.upper().replace('-', '_')}_{key}"

    def client_credential(self) -> str | dict[str, str]:
        """MSAL client credential from env: secret, or cert path + thumbprint."""
        secret = os.environ.get(self._env("CLIENT_SECRET"))
        if secret:
            return secret
        cert = os.environ.get(self._env("CLIENT_CERT_PATH"))
        thumb = os.environ.get(self._env("CLIENT_CERT_THUMBPRINT"))
        if cert and thumb:
            return {"private_key": Path(cert).read_text(), "thumbprint": thumb}
        raise ConfigError(
            f"profile {self.name!r}: set {self._env('CLIENT_SECRET')} or "
            f"{self._env('CLIENT_CERT_PATH')} + {self._env('CLIENT_CERT_THUMBPRINT')}"
        )


def profiles_path() -> Path:
    env = os.environ.get("CKM365_PROFILES")
    if env:
        return Path(env).expanduser()
    return Path("~/.config/ckm365/profiles.toml").expanduser()


def state_dir() -> Path:
    base = Path(os.environ.get("XDG_STATE_HOME", "~/.local/state")).expanduser()
    path = base / "ckm365"
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path, 0o700)  # enforce even when the dir pre-existed looser
    return path


def load_profiles(path: Path | None = None) -> dict[str, Profile]:
    path = path or profiles_path()
    if not path.exists():
        raise ConfigError(
            f"no profiles file at {path} — copy profiles.example.toml there "
            "(or set CKM365_PROFILES)"
        )
    entries = tomllib.loads(path.read_text()).get("profiles") or {}
    if not entries:
        raise ConfigError(f"{path} defines no [profiles.<name>] tables")
    profiles: dict[str, Profile] = {}
    for name, entry in entries.items():
        unknown = set(entry) - _PROFILE_KEYS
        if unknown:
            raise ConfigError(f"profile {name!r}: unknown key(s) {sorted(unknown)}")
        profiles[name] = Profile(name=name, **entry)
    return profiles


def resolve_profile(profiles: dict[str, Profile], name: str | None) -> Profile:
    if name is not None:
        if name not in profiles:
            raise ConfigError(
                f"unknown account {name!r}; configured: {', '.join(sorted(profiles))}"
            )
        return profiles[name]
    if len(profiles) == 1:
        return next(iter(profiles.values()))
    raise ConfigError(
        "several profiles are configured "
        f"({', '.join(sorted(profiles))}) — pass account=<name>"
    )
