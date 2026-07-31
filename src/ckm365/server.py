"""CLI and MCPServer/stdio front door (mcp>=2.0 — mcp.server.mcpserver
does not exist in 1.x). All logging goes to stderr — stdout belongs to
the MCP protocol."""

import argparse
import logging
import sys
from pathlib import Path

from . import __version__, admin
from .auth import Auth, AuthError, NeedsLogin
from .config import ConfigError, load_profiles, resolve_profile
from .graph import GraphError
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
                       help="comma-separated presets: mail, calendar, teams, all. "
                            "'all' means mail+calendar; teams is read-only "
                            "discovery on its own consent tier, so ask for "
                            "it by name (see scripts/add-teams-scopes.sh)")
    serve.add_argument("--write", action="store_true",
                       help="expose write tools (drafts, calendar writes)")
    serve.add_argument("--enable-send", action="store_true",
                       help="expose send_draft and attendee-bearing event "
                            "writes (requires --write and Mail.Send consent)")
    serve.add_argument("--account", default=None,
                       help="pin every call to one profile")

    watch = sub.add_parser(
        "watch", help="poll (read-only) until matching mail arrives — exit 0 "
                      "on match, 3 on timeout; run as a background task")
    watch.add_argument("--from", dest="from_addresses", action="append",
                       metavar="ADDR", help="sender to match (repeatable)")
    watch.add_argument("--contains", default=None, metavar="TEXT",
                       help="subject substring to match")
    watch.add_argument("--folder", default="inbox")
    watch.add_argument("--timeout", type=float, default=3600,
                       help="seconds before giving up (default 3600)")
    watch.add_argument("--poll", type=float, default=15,
                       help="seconds between delta polls (default 15)")
    watch.add_argument("--account", default=None, help="profile name")
    watch.add_argument("--mailbox", default=None,
                       help="mailbox (default: the signed-in user)")

    for name, help_ in (("login", "device-code login for a profile"),
                        ("logout", "clear a profile's token cache")):
        p = sub.add_parser(name, help=help_)
        p.add_argument("profile", nargs="?", default=None,
                       help="profile name (optional when only one is configured)")
        if name == "login":
            p.add_argument("--send", action="store_true",
                           help="also consent to the Mail.Send scopes")

    admin.add_parsers(sub)  # mailbox / app / doctor (CKM-13)

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, stream=sys.stderr,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")

    try:
        if args.command == "serve":
            if args.enable_send and not args.write:
                parser.error("--enable-send requires --write")
            _serve(args)
            return
        if args.command == "watch":
            raise SystemExit(_watch(args))
        if args.command in admin.COMMANDS:
            raise SystemExit(admin.run(args))
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
    try:
        from mcp.server.mcpserver import MCPServer
        from mcp.types import ToolAnnotations
    except ImportError as exc:
        raise SystemExit(
            "ckm365 serve needs the MCP SDK (>=2.0), which is an optional "
            "extra — install with: pip install 'ckm365[mcp]'  (uv: add the "
            "'mcp' extra, or `uv sync` in a source checkout, whose dev "
            "group includes it)") from exc

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


def _watch(args: argparse.Namespace) -> int:
    """Background-watch process: exit 0 on matching mail (the harness wakes
    the agent), 3 on timeout, 1 on error. Read-only Ctx; output carries
    counts and truncated ids only — never subjects, senders, or bodies."""
    from .tools import watch as watch_tools

    ctx = Ctx.create(profiles_path=args.profiles)
    try:
        res = watch_tools.wait_for_message(
            ctx, timeout_s=args.timeout, poll_s=args.poll,
            folder=args.folder, from_addresses=args.from_addresses,
            subject_contains=args.contains, account=args.account,
            mailbox=args.mailbox)
    except GraphError as exc:
        print(f"ckm365 watch: {exc}", file=sys.stderr)
        return 1
    if res["timed_out"]:
        print(f"ckm365 watch: no matching mail after {args.timeout:g}s")
        return 3
    ids = ",".join(m.id[:12] for m in res["messages"][:5])
    print(f"ckm365 watch: matched={res['matched']} ids={ids}")
    return 0
