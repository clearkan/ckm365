"""Thin Microsoft Graph REST client: one httpx.Client, retry, paging, errors.

Retry policy (from the Softeria reference study, docs/reference-notes.md):
429 retries on any method honouring Retry-After (Graph throttles before
executing, so the side effect never landed); 503/504/transport errors retry
on idempotent methods only; everything else surfaces immediately.

Transient 5xx gets a LONGER budget than throttling (CKM-35). Graph answers
`ErrorInternalServerTransientError` for a cold or large mailbox — a filtered
`list_messages` on a high-volume inbox hit it twice in a row and surfaced as
a hard failure, because three sub-second retries all landed inside the same
blip. Same retry path, more patience: 5 attempts on a ~1s base instead of 3
on a 0.2s one (~6s expected, ~17s worst case, still far under a tool
timeout).
"""

import email.utils
import logging
import random
import time
from collections.abc import Iterator, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

import httpx

from .auth import Auth

log = logging.getLogger("ckm365")

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
_IDEMPOTENT = {"GET", "HEAD", "PUT", "DELETE"}
_MAX_RETRIES = 3
_MAX_TRANSIENT_RETRIES = 5  # 503/504 outlive throttling blips — see above
_BASE_BACKOFF = 0.2
_TRANSIENT_BACKOFF = 1.0
_MAX_BACKOFF = 5.0
_RETRY_AFTER_CAP = 60.0
_MAX_SEGMENT = 1024
_BATCH_LIMIT = 20  # Graph's hard cap on sub-requests per /$batch


class GraphError(Exception):
    def __init__(self, status: int, code: str, message: str,
                 request_id: str | None = None) -> None:
        self.status, self.code, self.message, self.request_id = \
            status, code, message, request_id
        super().__init__(f"Graph {status} {code}: {message}")


def encode_segment(value: str, name: str = "path segment") -> str:
    """Validate and percent-encode one URL path segment (mailbox, message id)."""
    v = (value or "").strip()
    if (not v or v in {".", ".."} or len(v) > _MAX_SEGMENT
            or any(ord(c) < 33 or ord(c) == 127 for c in v)):
        raise ValueError(f"invalid {name}: {v[:60]!r}")
    return quote(v, safe="")


def mailbox_path(mailbox: str, suffix: str) -> str:
    # Unlike message/event ids, a mailbox (UPN/smtp) never contains URL
    # delimiters — reject rather than encode them (lifted from ClearKan).
    if any(c in '/\\?#%' for c in mailbox or ""):
        raise ValueError(f"invalid mailbox: {mailbox[:60]!r}")
    return f"/users/{encode_segment(mailbox, 'mailbox')}/{suffix.lstrip('/')}"


def _retry_after(value: str | None) -> float | None:
    if not value:
        return None
    v = value.strip()
    if v.isdigit():
        return min(float(v), _RETRY_AFTER_CAP)
    try:
        dt = email.utils.parsedate_to_datetime(v)
    except (TypeError, ValueError):
        return None
    return min(max((dt - datetime.now(UTC)).total_seconds(), 0.0), _RETRY_AFTER_CAP)


class Graph:
    def __init__(self, auth: Auth, *, timeout: float = 30.0,
                 transport: httpx.BaseTransport | None = None) -> None:
        self.auth = auth
        self._client = httpx.Client(
            base_url=GRAPH_BASE, timeout=timeout, transport=transport)

    def close(self) -> None:
        """Close the underlying httpx client and its connection pool.
        Idempotent. Prefer Ctx.close(), which closes every cached Graph."""
        self._client.close()

    def request(self, method: str, path: str, *,
                params: Mapping[str, str] | None = None,
                json: Any = None,
                headers: Mapping[str, str] | None = None) -> dict[str, Any] | None:
        resp = self._send(method, path, params=params, json=json, headers=headers)
        return resp.json() if resp.content else None

    def content(self, path: str, *, params: Mapping[str, str] | None = None,
                headers: Mapping[str, str] | None = None) -> str:
        """GET a resource whose body is NOT JSON (meeting transcripts come
        back as VTT text). Same auth and retry policy as request()."""
        return self._send("GET", path, params=params, headers=headers).text

    def _send(self, method: str, path: str, *,
              params: Mapping[str, str] | None = None,
              json: Any = None,
              headers: Mapping[str, str] | None = None) -> httpx.Response:
        method = method.upper()
        attempt = 0
        while True:
            hdrs = {"Authorization": f"Bearer {self.auth.token()}", **(headers or {})}
            resp: httpx.Response | None = None
            try:
                resp = self._client.request(
                    method, path, params=params, json=json, headers=hdrs)
            except httpx.TransportError:
                if method not in _IDEMPOTENT or attempt >= _MAX_RETRIES:
                    raise
            transient = resp is not None and resp.status_code in (503, 504)
            budget = _MAX_TRANSIENT_RETRIES if transient else _MAX_RETRIES
            if resp is not None:
                retriable = resp.status_code == 429 or (
                    transient and method in _IDEMPOTENT)
                if not retriable:
                    if resp.is_success:
                        return resp
                    raise self._error(resp)
                if attempt >= budget:
                    raise self._error(resp)
            delay = _retry_after(resp.headers.get("retry-after")) \
                if resp is not None and resp.status_code == 429 else None
            if delay is None:
                base = _TRANSIENT_BACKOFF if transient else _BASE_BACKOFF
                delay = random.uniform(0, min(_MAX_BACKOFF, base * 2 ** attempt))
            log.warning("graph retry %d/%d after %s (sleep %.1fs)", attempt + 1,
                        budget, resp.status_code if resp else "transport error",
                        delay)
            time.sleep(delay)
            attempt += 1

    def get(self, path: str, **kw: Any) -> dict[str, Any]:
        return self.request("GET", path, **kw) or {}

    def post(self, path: str, **kw: Any) -> dict[str, Any] | None:
        return self.request("POST", path, **kw)

    def patch(self, path: str, **kw: Any) -> dict[str, Any]:
        return self.request("PATCH", path, **kw) or {}

    def batch(self, requests: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
        """Run many sub-requests through /$batch, 20 at a time (Graph's cap).

        Each request is {"method", "url", "body"?}, where url is relative to
        the service root ("/users/x/messages/y") — the same shape
        mailbox_path() produces. Returns one {"status", "body"} per input
        request IN INPUT ORDER: Graph answers out of order, so sub-responses
        are re-keyed here by their request id.

        A failing SUB-request is data, not an exception — the batch itself
        succeeds and each caller decides what a per-item 404 means. The one
        exception is throttling: a sub-request answered 429 never executed,
        so it is re-sent once (the same reasoning that lets _send retry 429
        on any method). Non-idempotent 5xx sub-failures are reported, not
        retried, because we cannot know whether the side effect landed.
        """
        out: list[dict[str, Any]] = []
        for start in range(0, len(requests), _BATCH_LIMIT):
            chunk = requests[start:start + _BATCH_LIMIT]
            answers = self._batch_chunk(chunk)
            retry = [i for i, a in enumerate(answers) if a["status"] == 429]
            if retry:
                log.warning("graph batch: re-sending %d throttled sub-request(s)",
                            len(retry))
                time.sleep(random.uniform(0, _MAX_BACKOFF))
                for i, again in zip(retry, self._batch_chunk(
                        [chunk[i] for i in retry])):
                    answers[i] = again
            out += answers
        return out

    def _batch_chunk(self, chunk: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
        payload = {"requests": [
            {"id": str(i), "method": r["method"], "url": r["url"],
             **({"body": r["body"],
                 "headers": {"Content-Type": "application/json"}}
                if r.get("body") is not None else {})}
            for i, r in enumerate(chunk)]}
        answered = {str(a.get("id")): a for a in
                    (self.post("/$batch", json=payload) or {}).get("responses", [])}
        return [{"status": int((answered.get(str(i)) or {}).get("status") or 0),
                 "body": (answered.get(str(i)) or {}).get("body")}
                for i in range(len(chunk))]

    def paged(self, path: str, *, params: Mapping[str, str] | None = None,
              max_items: int = 100,
              headers: Mapping[str, str] | None = None) -> Iterator[dict[str, Any]]:
        """Yield collection items, following @odata.nextLink up to max_items."""
        url: str | None = path
        count = 0
        while url:
            page = self.get(url, params=params, headers=headers)
            params = None  # nextLink carries the full query string
            for item in page.get("value", []):
                yield item
                count += 1
                if count >= max_items:
                    return
            url = page.get("@odata.nextLink")
            if url and not url.startswith(GRAPH_BASE):
                # The bearer token goes wherever we follow — pin the host.
                raise GraphError(0, "unsafe_next_link",
                                 "refusing to follow @odata.nextLink off "
                                 f"{GRAPH_BASE}: {url[:80]}")

    @staticmethod
    def _error(resp: httpx.Response) -> GraphError:
        code = message = ""
        try:
            err = resp.json().get("error") or {}
            code, message = str(err.get("code", "")), str(err.get("message", ""))
        except ValueError:
            pass
        return GraphError(resp.status_code, code, message,
                          resp.headers.get("request-id"))
