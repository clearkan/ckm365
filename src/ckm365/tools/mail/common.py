"""Plumbing every mail module shares: paths, headers, /$batch fan-out.

Nothing here is a tool. The batch helpers are the convention the triage
tools and get_message_headers are built on — one Graph call per message
id, 20 to a round trip, per-id outcomes, and one failure never stranding
the rest of the batch.
"""

import logging

from ...graph import Graph, encode_segment as _seg, mailbox_path as _path

log = logging.getLogger("ckm365")


_MAX_BATCH_IDS = 200  # one triage call = at most 10 Graph batches


def prefer(body_format: str) -> dict[str, str]:
    if body_format not in ("text", "html"):
        raise ValueError("body_format must be 'text' or 'html'")
    return {"Prefer": f'outlook.body-content-type="{body_format}"'}


def message_path(mailbox: str, message_id: str, suffix: str = "") -> str:
    return _path(mailbox, f"messages/{_seg(message_id, 'message_id')}{suffix}")


def require_draft(g: Graph, path: str, verb: str,
                  select: str = "id,isDraft") -> dict:
    """The draft-only invariant lives here: fetch and refuse non-drafts."""
    current = g.get(path, params={"$select": select})
    if not current.get("isDraft"):
        raise ValueError(f"refusing to {verb} a non-draft message")
    return current


def batch_ids(message_ids: list[str]) -> list[str]:
    """Validate and de-duplicate the id list every triage tool takes.

    Duplicates collapse (patching one message twice in a batch is
    pointless), so "ok" counts DISTINCT messages and may be lower than the
    number of ids passed in.
    """
    if isinstance(message_ids, str):  # a bare id is the obvious LLM mistake,
        raise ValueError(            # and would otherwise batch its letters
            "message_ids must be a LIST of message ids, not a single string")
    ids = list(dict.fromkeys((m or "").strip() for m in message_ids or []))
    if not ids:
        raise ValueError("message_ids is empty")
    if len(ids) > _MAX_BATCH_IDS:
        raise ValueError(f"at most {_MAX_BATCH_IDS} message ids per call, got "
                         f"{len(ids)} — split it into several calls")
    for message_id in ids:
        _seg(message_id, "message_id")  # reject junk before any Graph call
    return ids


def batch_error(result: dict) -> str:
    err = (result.get("body") or {}).get("error") or {}
    detail = f"{err.get('code') or ''} {err.get('message') or ''}".strip()
    return f"{result['status']} {detail}".strip()[:200]


def apply_each(g: Graph, mb: str, ids: list[str], method: str,
               suffix: str = "", body: dict | None = None
               ) -> tuple[list[tuple[str, dict]], list[dict]]:
    """Run one Graph call per message id through /$batch; split the outcome
    into (succeeded [(id, response body)], failed [{"id", "error"}])."""
    results = g.batch([{"method": method, "url": message_path(mb, i, suffix),
                        **({"body": body} if body is not None else {})}
                       for i in ids])
    ok: list[tuple[str, dict]] = []
    failed: list[dict] = []
    for message_id, result in zip(ids, results):
        if 200 <= result["status"] < 300:
            ok.append((message_id, result["body"] or {}))
        else:
            failed.append({"id": message_id, "error": batch_error(result)})
    return ok, failed


def outcome(tool: str, mb: str, ok: list, failed: list, **extra) -> dict:
    log.info("tool=%s mailbox=%r ok=%d failed=%d", tool, mb, len(ok), len(failed))
    return {"ok": len(ok), "failed": failed, **extra}
