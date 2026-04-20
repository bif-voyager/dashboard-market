from __future__ import annotations

import asyncio
import random
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

import httpx


class UpstreamError(RuntimeError):
    def __init__(self, source: str, status_code: int, message: str) -> None:
        super().__init__(message)
        self.source = source
        self.status_code = status_code
        self.message = message


class PublicApiClient:
    def __init__(
        self,
        *,
        base_url: str,
        source: str,
        timeout_seconds: int,
        max_attempts: int = 6,
        min_interval_seconds: float = 0.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.source = source
        self.max_attempts = max(1, max_attempts)
        self.min_interval_seconds = max(0.0, min_interval_seconds)
        self._request_lock = asyncio.Lock()
        self._next_request_ready_at = 0.0
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(timeout_seconds),
            headers={"User-Agent": "market-dashboard/1.0"},
        )

    async def close(self) -> None:
        await self.client.aclose()

    async def _wait_for_request_slot(self) -> None:
        if self.min_interval_seconds <= 0:
            return

        async with self._request_lock:
            loop = asyncio.get_running_loop()
            now = loop.time()
            wait_seconds = self._next_request_ready_at - now
            if wait_seconds > 0:
                await asyncio.sleep(wait_seconds)
            self._next_request_ready_at = loop.time() + self.min_interval_seconds

    def _backoff_delay(self, attempt: int) -> float:
        return min(8.0, (0.4 * (2 ** (attempt - 1))) + random.uniform(0.1, 0.35))

    def _retry_after_seconds(self, response: httpx.Response) -> float | None:
        retry_after = response.headers.get("Retry-After")
        if not retry_after:
            return None

        try:
            return max(float(retry_after.strip()), 0.0)
        except ValueError:
            pass

        try:
            retry_at = parsedate_to_datetime(retry_after)
        except (TypeError, ValueError, IndexError):
            return None

        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=UTC)
        return max((retry_at.astimezone(UTC) - datetime.now(UTC)).total_seconds(), 0.0)

    async def get_json(self, path: str, *, params: dict[str, Any] | None = None) -> Any:
        attempt = 0
        while True:
            attempt += 1
            try:
                await self._wait_for_request_slot()
                response = await self.client.get(path, params=params)
                if response.status_code in {429, 500, 502, 503, 504} and attempt < self.max_attempts:
                    retry_after = self._retry_after_seconds(response) or 0.0
                    await asyncio.sleep(max(self._backoff_delay(attempt), retry_after))
                    continue
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as exc:
                raise UpstreamError(
                    self.source,
                    exc.response.status_code,
                    f"{self.source} returned {exc.response.status_code} for {path}",
                ) from exc
            except httpx.HTTPError as exc:
                if attempt < self.max_attempts:
                    await asyncio.sleep(self._backoff_delay(attempt))
                    continue
                raise UpstreamError(self.source, 0, f"{self.source} request failed for {path}") from exc
            except Exception as exc:  # pragma: no cover - defensive network guard
                if attempt < self.max_attempts:
                    await asyncio.sleep(self._backoff_delay(attempt))
                    continue
                raise UpstreamError(self.source, 0, f"{self.source} request failed for {path}") from exc
