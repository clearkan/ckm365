"""Shared tool context and the front-door binder.

Ctx carries the profiles, lazily-built Graph clients, and the write flag.
bind() turns a tool function into a ctx-less callable whose signature both
FastMCP and pydantic-ai can introspect, and is the single place tool
invocations are logged (names and ids only — never bodies or tokens).
"""

import functools
import inspect
import logging
from dataclasses import dataclass, field
from pathlib import Path

from ..auth import Auth, NeedsLogin
from ..config import ConfigError, Profile, load_profiles, resolve_profile
from ..graph import Graph

log = logging.getLogger("ckm365")

_LOG_KEYS = ("account", "mailbox", "folder", "message_id", "event_id",
             "reply_all", "file_path", "to", "attendees")


class WriteDisabled(RuntimeError):
    pass


class SendDisabled(RuntimeError):
    pass


@dataclass
class Ctx:
    profiles: dict[str, Profile]
    write_enabled: bool = False
    send_enabled: bool = False
    account: str | None = None  # pin from --account
    _graphs: dict[str, Graph] = field(default_factory=dict, repr=False)

    @classmethod
    def create(cls, *, write: bool = False, send: bool = False,
               account: str | None = None,
               profiles_path: Path | None = None) -> "Ctx":
        profiles = load_profiles(profiles_path)
        if account:
            resolve_profile(profiles, account)  # fail fast on typos
        return cls(profiles=profiles, write_enabled=write, send_enabled=send,
                   account=account)

    def profile(self, account: str | None = None) -> Profile:
        if self.account and account and account != self.account:
            raise ConfigError(
                f"this server is pinned to profile {self.account!r}; "
                f"refusing account {account!r}")
        return resolve_profile(self.profiles, account or self.account)

    def graph(self, account: str | None = None) -> Graph:
        p = self.profile(account)
        if p.name not in self._graphs:
            self._graphs[p.name] = Graph(
                Auth(p, read_only=not self.write_enabled, send=self.send_enabled))
        return self._graphs[p.name]

    def target(self, account: str | None, mailbox: str | None) -> tuple[Graph, str]:
        """Resolve (graph, mailbox): explicit > profile default > signed-in user."""
        p = self.profile(account)
        g = self.graph(account)
        mb = mailbox or p.default_mailbox or g.auth.username()
        if not mb:
            raise NeedsLogin(
                f"profile {p.name!r}: no mailbox — run 'ckm365 login {p.name}' "
                "or set default_mailbox in profiles.toml")
        return g, mb

    def require_write(self) -> None:
        if not self.write_enabled:
            raise WriteDisabled(
                "write tools are disabled; start the server with --write")

    def require_send(self, account: str | None = None) -> None:
        """Gate a send-tier operation: server flags first, then the target
        profile's allow_send cap (call sites pass their account argument)."""
        self.require_write()
        if not self.send_enabled:
            raise SendDisabled(
                "this operation delivers mail to recipients; start the "
                "server with --write --enable-send")
        profile = self.profile(account)
        if not profile.allow_send:
            raise SendDisabled(
                f"profile {profile.name!r} sets allow_send = false in "
                "profiles.toml — the send tier is capped for this profile "
                "regardless of server flags")


def bind(fn, ctx: Ctx):
    """Bind ctx away, preserving an introspectable signature, and log the call.

    When the Ctx is pinned to one profile, the account parameter is dropped
    from the exposed schema entirely (and a mismatched value raises in
    Ctx.profile) — the pin is an isolation control, not a default.
    Recipient-ish list values are logged as counts, never addresses.
    """
    hidden = {"ctx"} | ({"account"} if ctx.account else set())

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        detail = " ".join(
            f"{k}#={len(v)}" if isinstance(v, list) else f"{k}={v!r}"
            for k in _LOG_KEYS if (v := kwargs.get(k)) is not None)
        log.info("tool=%s %s", fn.__name__, detail)
        return fn(ctx, *args, **kwargs)

    sig = inspect.signature(fn)
    wrapper.__signature__ = sig.replace(
        parameters=[p for n, p in sig.parameters.items() if n not in hidden])
    wrapper.__annotations__ = {
        k: v for k, v in fn.__annotations__.items() if k not in hidden}
    return wrapper
