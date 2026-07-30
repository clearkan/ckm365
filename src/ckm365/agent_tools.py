"""pydantic-ai front door: register the same tool functions in-process.

Duck-typed — anything exposing .tool_plain(fn) works, so pydantic-ai is
not a dependency of this package.
"""

from pathlib import Path

from .tools import Ctx, bind, tools_for


def register(agent, *, presets=("mail", "calendar"), write: bool = False,
             send: bool = False, account: str | None = None,
             profiles_path: Path | None = None) -> Ctx:
    """Register ckm365 tools on a pydantic-ai Agent; returns the Ctx used.

    send=True (requires write=True) adds send_draft and unlocks
    attendee-bearing event writes — the profile needs Mail.Send consent."""
    ctx = Ctx.create(write=write, send=send, account=account,
                     profiles_path=profiles_path)
    for fn in tools_for(presets, write=write, send=send):
        agent.tool_plain(bind(fn, ctx))
    return ctx
