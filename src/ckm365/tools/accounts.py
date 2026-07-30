"""Account/profile introspection — registered with every preset."""

from .context import Ctx


def list_accounts(ctx: Ctx) -> list[dict]:
    """List the configured account profiles: name (use as the `account`
    parameter on other tools), description, auth mode, default mailbox,
    and whether a cached login exists. Reads local config only."""
    profiles = [ctx.profile()] if ctx.account else list(ctx.profiles.values())
    out = []
    for p in profiles:
        username = ctx.graph(p.name).auth.username()
        out.append({
            "account": p.name,
            "description": p.description,
            "auth": p.auth,
            "default_mailbox": p.default_mailbox,
            "signed_in": bool(username) if p.auth == "device_code" else None,
            "signed_in_as": username,
        })
    return out
