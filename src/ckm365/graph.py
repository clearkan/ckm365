"""Thin Microsoft Graph REST client: one httpx.Client, retry, paging, errors.

Retry policy (from the Softeria reference study, docs/reference-notes.md):
429 retries on any method honouring Retry-After (Graph throttles before
executing, so the side effect never landed); 503/504/transport errors retry
on idempotent methods only; everything else surfaces immediately.
"""

import email.utils
import logging
import random
import time
from collections.abc import Iterator, Mapping
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

import httpx

from .auth import Auth

log = logging.getLogger("ckm365")

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
_IDEMPOTENT = {"GET", "HEAD", "PUT", "DELETE"}
_MAX_RETRIES = 3
_BASE_BACKOFF = 0.2
_MAX_BACKOFF = 5.0
_RETRY_AFTER_CAP = 60.0
_MAX_SEGMENT = 1024


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

    def request(self, method: str, path: str, *,
                params: Mapping[str, str] | None = None,
                json: Any = None,
                headers: Mapping[str, str] | None = None) -> dict[str, Any] | None:
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
            if resp is not None:
                retriable = resp.status_code == 429 or (
                    resp.status_code in (503, 504) and method in _IDEMPOTENT)
                if not retriable:
                    if resp.is_success:
                        return resp.json() if resp.content else None
                    raise self._error(resp)
                if attempt >= _MAX_RETRIES:
                    raise self._error(resp)
            delay = _retry_after(resp.headers.get("retry-after")) \
                if resp is not None and resp.status_code == 429 else None
            if delay is None:
                delay = random.uniform(0, min(_MAX_BACKOFF, _BASE_BACKOFF * 2 ** attempt))
            log.warning("graph retry %d/%d after %s (sleep %.1fs)", attempt + 1,
                        _MAX_RETRIES, resp.status_code if resp else "transport error",
                        delay)
            time.sleep(delay)
            attempt += 1

    def get(self, path: str, **kw: Any) -> dict[str, Any]:
        return self.request("GET", path, **kw) or {}

    def post(self, path: str, **kw: Any) -> dict[str, Any] | None:
        return self.request("POST", path, **kw)

    def patch(self, path: str, **kw: Any) -> dict[str, Any]:
        return self.request("PATCH", path, **kw) or {}

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
