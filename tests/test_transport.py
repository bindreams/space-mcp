"""Tests for the shared per-request deadline helper."""

import asyncio

import httpx
import pytest

from space.transport import ApiTimeoutError, DEFAULT_REQUEST_TIMEOUT, send_with_deadline


class TestSendWithDeadline:

    async def test_returns_response_on_success(self, httpx_mock):
        httpx_mock.add_response(json={"ok": True})
        async with httpx.AsyncClient() as http:
            resp = await send_with_deadline(http, "GET", "https://x/api", 5.0, service="Space API")
        assert resp.json() == {"ok": True}

    async def test_translates_httpx_timeout_to_api_timeout_error(self, httpx_mock):
        httpx_mock.add_exception(httpx.ReadTimeout("read timed out"))
        async with httpx.AsyncClient() as http:
            with pytest.raises(ApiTimeoutError) as ei:
                await send_with_deadline(http, "GET", "https://x/api", 5.0, service="Patronus")
        assert "Patronus did not respond" in str(ei.value)

    async def test_deadline_fires_on_stall(self, httpx_mock):
        """A response that never arrives is aborted at the deadline (the sanctioned
        use of a timeout: a failure bound on a remote response that may never come)."""

        async def never_responds(request):
            await asyncio.Event().wait()  # cancelled by the deadline

        httpx_mock.add_callback(never_responds, is_reusable=True)
        async with httpx.AsyncClient() as http:
            with pytest.raises(ApiTimeoutError) as ei:
                await send_with_deadline(http, "GET", "https://x/api", 0.05, service="Space API")
        assert "Space API did not respond" in str(ei.value)

    def test_is_httpx_timeout_subclass(self):
        # Existing best-effort `except httpx.TimeoutException` handlers must still catch it.
        assert issubclass(ApiTimeoutError, httpx.TimeoutException)

    def test_default_timeout_is_sane(self):
        assert DEFAULT_REQUEST_TIMEOUT == 30.0
