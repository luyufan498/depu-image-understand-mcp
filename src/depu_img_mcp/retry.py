"""Exponential backoff retry for transient HTTP errors (429 / 5xx / network)."""
from __future__ import annotations

import asyncio
import logging

import httpx

log = logging.getLogger("depu.retry")

_RETRY_STATUS = {429, 500, 502, 503, 504}


async def request_with_retry(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    json: dict | None = None,
    headers: dict | None = None,
    timeout: float,
    max_retries: int = 3,
    backoff_base_ms: int = 500,
) -> httpx.Response:
    """Make an HTTP request, retrying on transient failures."""
    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            resp = await client.request(
                method, url, json=json, headers=headers, timeout=timeout
            )
            if resp.status_code not in _RETRY_STATUS:
                return resp
            log.warning(
                "transient %s on %s (attempt %d/%d)",
                resp.status_code, url, attempt + 1, max_retries + 1,
            )
        except (httpx.TransportError, httpx.TimeoutException) as e:
            last_exc = e
            log.warning("network error on %s: %s (attempt %d/%d)",
                        url, e, attempt + 1, max_retries + 1)

        if attempt < max_retries:
            delay = (backoff_base_ms / 1000) * (2 ** attempt)
            await asyncio.sleep(delay)

    # final attempt failed with retryable status
    if "resp" in locals():
        return resp  # type: ignore[name-defined]
    raise last_exc  # type: ignore[misc]
