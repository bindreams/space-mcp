"""Shared per-request deadline for outbound API calls.

Both ``SpaceClient`` and ``PatronusClient`` route their requests through
``send_with_deadline`` so a stalled backend can never wedge a call indefinitely.
The deadline is the failure bound on a remote response — the one legitimate use
of a timeout, not code-to-code synchronization.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

DEFAULT_REQUEST_TIMEOUT = 30.0  # seconds; total deadline applied to every outbound API request


class ApiTimeoutError(httpx.TimeoutException):
    """An outbound API request exceeded its per-request deadline.

    Subclasses httpx.TimeoutException so existing best-effort handlers that catch
    httpx timeouts continue to degrade gracefully. The message names the service
    (e.g. "Space API", "Patronus") so timeouts are never misattributed.
    """


async def send_with_deadline(
    http: httpx.AsyncClient,
    method: str,
    url: str,
    timeout: float,
    *,
    service: str,
    **kwargs: Any,
) -> httpx.Response:
    """Send one request bounded by an overall ``timeout`` (seconds).

    ``http.request`` reads the full non-streaming body before returning, so the
    deadline covers connect + headers + body — unlike httpx's per-operation timeout,
    which only bounds the gap between chunks. On cancellation httpx closes the
    in-flight connection rather than returning it to the pool.

    Raises:
        ApiTimeoutError: if the response does not complete within ``timeout``.
    """
    try:
        async with asyncio.timeout(timeout):
            return await http.request(method, url, **kwargs)
    except (TimeoutError, httpx.TimeoutException) as exc:
        raise ApiTimeoutError(f"{service} did not respond after {timeout:g}s") from exc
