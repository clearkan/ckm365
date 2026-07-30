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
                 "description"}
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
