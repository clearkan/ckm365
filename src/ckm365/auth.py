"""MSAL wrapper: one app per profile, tenant-pinned authority, file token cache.

The cache is reloaded from disk before every acquire and persisted after any
change (Graph rotates refresh tokens on silent refresh; several concurrent
stdio server processes share the cache file).
"""

import contextlib
import logging
import os
import sys
from pathlib import Path

import msal

try:
    import fcntl  # POSIX only; on other platforms the lock degrades to no-op
except ImportError:  # pragma: no cover
    fcntl = None

from .config import Profile, state_dir

log = logging.getLogger("ckm365")

APP_ONLY_SCOPES = ["https://graph.microsoft.com/.default"]
# offline_access/openid/profile are reserved — MSAL adds them itself.
DELEGATED_RW = ["Mail.ReadWrite", "Mail.ReadWrite.Shared",
                "Calendars.ReadWrite", "Calendars.ReadWrite.Shared"]
DELEGATED_RO = ["Mail.Read", "Mail.Read.Shared",
                "Calendars.Read", "Calendars.Read.Shared"]
# Send is a distinct tier: requested only when send mode is enabled, and
# never folded into the always-consented login set (security review).
DELEGATED_SEND = DELEGATED_RW + ["Mail.Send", "Mail.Send.Shared"]


class NeedsLogin(RuntimeError):
    pass


class AuthError(RuntimeError):
    pass


class Auth:
    def __init__(self, profile: Profile, *, read_only: bool = True,
                 send: bool = False, cache_dir: Path | None = None) -> None:
        self.profile = profile
        self._delegated = profile.auth == "device_code"
        if not self._delegated:
            self.scopes = APP_ONLY_SCOPES
        elif send and profile.allow_send:
            # allow_send = false downscopes even in send mode: a capped
            # profile never requests (or silently refreshes) Mail.Send.
            self.scopes = DELEGATED_SEND
        else:
            self.scopes = DELEGATED_RO if read_only else DELEGATED_RW
        self._cache = msal.SerializableTokenCache()
        self._cache_path = (cache_dir or state_dir()) / f"{profile.name}.msal.json"
        self._app: msal.ClientApplication | None = None

    def _application(self) -> msal.ClientApplication:
        if self._app is None:
            authority = f"https://login.microsoftonline.com/{self.profile.tenant_id}"
            if self._delegated:
                self._app = msal.PublicClientApplication(
                    self.profile.client_id, authority=authority, token_cache=self._cache)
            else:
                self._app = msal.ConfidentialClientApplication(
                    self.profile.client_id, authority=authority, token_cache=self._cache,
                    client_credential=self.profile.client_credential())
        return self._app

    @contextlib.contextmanager
    def _lock(self):
        """Cross-process lock on a sidecar file: two servers refreshing the
        same rotated refresh token must not clobber each other's persist."""
        if fcntl is None:  # pragma: no cover
            yield
            return
        self._cache_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd = os.open(self._cache_path.with_suffix(".lock"),
                     os.O_CREAT | os.O_WRONLY, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def _sole_account(self, app: msal.ClientApplication):
        """The one cached account for this profile, or None. More than one
        means nondeterministic identity — refuse (security review)."""
        accounts = app.get_accounts()
        if len(accounts) > 1:
            names = ", ".join(sorted(a.get("username", "?") for a in accounts))
            raise AuthError(
                f"multiple cached accounts for profile {self.profile.name!r} "
                f"({names}) — run: ckm365 logout {self.profile.name} "
                f"&& ckm365 login {self.profile.name}")
        return accounts[0] if accounts else None

    def _reload(self) -> None:
        if self._cache_path.exists():
            self._cache.deserialize(self._cache_path.read_text())

    def _persist(self) -> None:
        if not self._cache.has_state_changed:
            return
        self._cache_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self._cache_path.parent, 0o700)  # also when pre-existing
        tmp = self._cache_path.with_name(f".{self._cache_path.name}.{os.getpid()}.tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.write(fd, self._cache.serialize().encode())
        finally:
            os.close(fd)
        tmp.replace(self._cache_path)

    def token(self) -> str:
        with self._lock():
            self._reload()
            app = self._application()
            try:
                if self._delegated:
                    account = self._sole_account(app)
                    result = app.acquire_token_silent_with_error(
                        self.scopes, account=account) if account else None
                else:
                    result = app.acquire_token_for_client(scopes=self.scopes)
            finally:
                self._persist()
        if not result or "access_token" not in result:
            if self._delegated:
                detail = (result or {}).get("error_description", "no cached login")
                raise NeedsLogin(
                    f"profile {self.profile.name!r} needs a login "
                    f"(run: ckm365 login {self.profile.name}) — {detail}")
            raise AuthError(
                f"profile {self.profile.name!r} app-only token failed: "
                f"{(result or {}).get('error_description', 'unknown error')}")
        return result["access_token"]

    def username(self) -> str | None:
        """UPN of the signed-in delegated account, if any."""
        if not self._delegated:
            return None
        with self._lock():
            self._reload()
            account = self._sole_account(self._application())
        return account["username"] if account else None

    def login(self, *, send: bool = False) -> str:
        """Interactive device-code login (delegated) or credential check (app-only).

        Requests the ReadWrite scopes so one consent covers read + write;
        a read-only server start silently downscopes. Send consent is a
        deliberate extra step: pass send=True (CLI: login --send) — ignored
        for allow_send = false profiles, whose caches must never hold
        send-consented tokens.
        """
        if not self._delegated:
            self.token()
            return f"app-only credentials OK for {self.profile.name}"
        self._reload()
        app = self._application()
        flow = app.initiate_device_flow(
            scopes=DELEGATED_SEND if send and self.profile.allow_send
            else DELEGATED_RW)
        if "user_code" not in flow:
            raise AuthError(f"device flow failed: {flow.get('error_description', flow)}")
        print(f"\n{flow['message']}\n", file=sys.stderr, flush=True)
        result = app.acquire_token_by_device_flow(flow)
        if "access_token" not in result:
            raise AuthError(f"login failed: {result.get('error_description', result)}")
        # One identity per profile cache: evict any pre-existing different
        # account so accounts[0] can never mean the wrong user.
        claimed = ((result.get("id_token_claims") or {})
                   .get("preferred_username") or "").lower()
        if claimed:
            for extra in [a for a in app.get_accounts()
                          if a.get("username", "").lower() != claimed]:
                app.remove_account(extra)
        with self._lock():
            self._persist()
        account = self._sole_account(app)
        username = account.get("username", "unknown") if account else "unknown"
        log.info("logged in profile=%s account=%s", self.profile.name, username)
        return username

    def logout(self) -> None:
        with self._lock():
            self._reload()
            app = self._application()
            for account in app.get_accounts():
                app.remove_account(account)
            self._persist()
            self._cache_path.unlink(missing_ok=True)
