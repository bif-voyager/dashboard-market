from __future__ import annotations

import asyncio
import random
from typing import Any

import httpx


class UpstreamError(RuntimeError):
    def __init__(self, source: str, status_code: int, message: str) -> None:
        super().__init__(message)
        self.source = source
        self.status_code = status_code
        self.message = message


class PublicApiClient:
    def __init__(self, *, base_url: str, source: str, timeout_seconds: int) -> None:
        self.base_url = base_url.rstrip("/")
        self.source = source
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(timeout_seconds),
            headers={"User-Agent": "market-dashboard/1.0"},
        )

    async def close(self) -> None:
        await self.client.aclose()

    async def get_json(self, path: str, *, params: dict[str, Any] | None = None) -> Any:
        attempt = 0
        while True:
            attempt += 1
            try:
                response = await self.client.get(path, params=params)
                if response.status_code in {429, 500, 502, 503, 504} and attempt < 4:
                    await asyncio.sleep((0.4 * (2 ** (attempt - 1))) + random.uniform(0.1, 0.35))
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
                if attempt < 4:
                    await asyncio.sleep((0.4 * (2 ** (attempt - 1))) + random.uniform(0.1, 0.35))
                    continue
                raise UpstreamError(self.source, 0, f"{self.source} request failed for {path}") from exc
            except Exception as exc:  # pragma: no cover - defensive network guard
                if attempt < 4:
                    await asyncio.sleep((0.4 * (2 ** (attempt - 1))) + random.uniform(0.1, 0.35))
                    continue
                raise UpstreamError(self.source, 0, f"{self.source} request failed for {path}") from exc
