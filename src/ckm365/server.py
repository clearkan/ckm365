"""CLI and FastMCP/stdio front door. All logging goes to stderr —
stdout belongs to the MCP protocol."""

import argparse
import logging
import sys
from pathlib import Path

from . import __version__
from .auth import Auth, AuthError, NeedsLogin
from .config import ConfigError, load_profiles, resolve_profile
from .tools import Ctx, bind, tools_for

log = logging.getLogger("ckm365")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="ckm365", description="Minimal multi-tenant M365 Graph MCP server")
    parser.add_argument("--profiles", type=Path, default=None,
                        help="path to profiles.toml (default ~/.config/ckm365/)")
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="run the stdio MCP server")
    serve.add_argument("--preset", default="all",
                       help="comma-separated presets: mail, calendar, all")
    serve.add_argument("--write", action="store_true",
                       help="expose write tools (drafts, calendar writes)")
    serve.add_argument("--enable-send", action="store_true",
                       help="expose send_draft and attendee-bearing event "
                            "writes (requires --write and Mail.Send consent)")
    serve.add_argument("--account", default=None,
                       help="pin every call to one profile")

    for name, help_ in (("login", "device-code login for a profile"),
                        ("logout", "clear a profile's token cache")):
        p = sub.add_parser(name, help=help_)
        p.add_argument("profile", nargs="?", default=None,
                       help="profile name (optional when only one is configured)")
        if name == "login":
            p.add_argument("--send", action="store_true",
                           help="also consent to the Mail.Send scopes")

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, stream=sys.stderr,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")

    try:
        if args.command == "serve":
            if args.enable_send and not args.write:
                parser.error("--enable-send requires --write")
            _serve(args)
            return
        profile = resolve_profile(load_profiles(args.profiles), args.profile)
        auth = Auth(profile, read_only=False)
        if args.command == "login":
            print(f"logged in: {auth.login(send=args.send)}", file=sys.stderr)
        else:
            auth.logout()
            print(f"logged out: {profile.name}", file=sys.stderr)
    except (ConfigError, AuthError, NeedsLogin) as exc:
        raise SystemExit(f"ckm365: {exc}") from exc


def _serve(args: argparse.Namespace) -> None:
    from mcp.server.mcpserver import MCPServer
    from mcp.types import ToolAnnotations

    from .tools import SEND, WRITE

    ctx = Ctx.create(write=args.write, send=args.enable_send,
                     account=args.account, profiles_path=args.profiles)
    presets = [p.strip() for p in args.preset.split(",") if p.strip()]
    mcp = MCPServer("ckm365", version=__version__)
    write_fns = {f for fns in WRITE.values() for f in fns}
    send_fns = {f for fns in SEND.values() for f in fns}
    fns = tools_for(presets, write=args.write, send=args.enable_send)
    for fn in fns:
        mcp.add_tool(bind(fn, ctx), annotations=ToolAnnotations(
            read_only_hint=fn not in write_fns and fn not in send_fns,
            destructive_hint=fn in send_fns or None,
            open_world_hint=True))
    log.info("serving %d tools presets=%s write=%s send=%s profiles=%s",
             len(fns), ",".join(presets), args.write, args.enable_send,
             ",".join(sorted(ctx.profiles)))
    mcp.run()
