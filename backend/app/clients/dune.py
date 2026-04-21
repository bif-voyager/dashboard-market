from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.clients.base import UpstreamError
from app.config import Settings


@dataclass(slots=True)
class DuneQueryResult:
    query_id: int
    rows: list[dict[str, Any]]
    pages: int
    execution_id: str | None = None
    state: str | None = None
    submitted_at: str | None = None
    expires_at: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class DuneClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.api_key = (settings.dune_api_key or "").strip()
        self.client = httpx.AsyncClient(
            base_url=settings.dune_base_url.rstrip("/"),
            timeout=httpx.Timeout(settings.request_timeout_seconds),
            headers={
                "User-Agent": "market-dashboard/1.0",
                "X-DUNE-API-KEY": self.api_key,
            },
        )

    async def close(self) -> None:
        await self.client.aclose()

    async def get_latest_result(self, query_id: int) -> DuneQueryResult:
        if not self.api_key:
            raise UpstreamError("dune", 0, "DUNE_API_KEY is not configured")

        rows: list[dict[str, Any]] = []
        metadata: dict[str, Any] = {}
        execution_id = None
        state = None
        submitted_at = None
        expires_at = None
        offset = 0
        seen_offsets: set[int] = set()

        for page_index in range(self.settings.dune_max_pages):
            payload = await self._get_json(
                f"/query/{query_id}/results",
                params={
                    "limit": self.settings.dune_page_limit,
                    "offset": offset,
                },
            )
            result = payload.get("result") or {}
            batch = result.get("rows") or []
            if not isinstance(batch, list):
                raise UpstreamError("dune", 0, f"Dune query {query_id} returned an unexpected rows payload")

            rows.extend(batch)
            metadata = result.get("metadata") or metadata
            execution_id = payload.get("execution_id") or execution_id
            state = payload.get("state") or state
            submitted_at = payload.get("submitted_at") or submitted_at
            expires_at = payload.get("expires_at") or expires_at

            if state and "FAILED" in state:
                raise UpstreamError("dune", 0, f"Dune query {query_id} latest execution failed")
            if state and "EXPIRED" in state:
                raise UpstreamError("dune", 0, f"Dune query {query_id} latest result expired")

            next_offset = payload.get("next_offset") or result.get("next_offset")
            if next_offset is None:
                total_row_count = metadata.get("total_row_count")
                if total_row_count is not None and len(rows) < int(total_row_count) and batch:
                    next_offset = offset + len(batch)
                else:
                    return DuneQueryResult(
                        query_id=query_id,
                        rows=rows,
                        pages=page_index + 1,
                        execution_id=execution_id,
                        state=state,
                        submitted_at=submitted_at,
                        expires_at=expires_at,
                        metadata=metadata,
                    )

            next_offset = int(next_offset)
            if next_offset in seen_offsets or next_offset == offset:
                return DuneQueryResult(
                    query_id=query_id,
                    rows=rows,
                    pages=page_index + 1,
                    execution_id=execution_id,
                    state=state,
                    submitted_at=submitted_at,
                    expires_at=expires_at,
                    metadata=metadata,
                )
            seen_offsets.add(offset)
            offset = next_offset

        raise UpstreamError(
            "dune",
            0,
            f"Dune query {query_id} exceeded local pagination limit of {self.settings.dune_max_pages} pages",
        )

    async def execute_sql(self, sql: str) -> DuneQueryResult:
        if not self.api_key:
            raise UpstreamError("dune", 0, "DUNE_API_KEY is not configured")

        payload = await self._post_json(
            "/sql/execute",
            json_payload={
                "sql": sql,
                "performance": self.settings.dune_sql_performance_tier,
            },
        )
        execution_id = payload.get("execution_id")
        if not execution_id:
            raise UpstreamError("dune", 0, "Dune SQL execution did not return an execution_id")

        status = await self._wait_for_execution(str(execution_id))
        return await self._get_execution_result(str(execution_id), status)

    async def _get_execution_result(self, execution_id: str, status: dict[str, Any]) -> DuneQueryResult:
        rows: list[dict[str, Any]] = []
        metadata: dict[str, Any] = {}
        offset = 0
        seen_offsets: set[int] = set()

        for page_index in range(self.settings.dune_max_pages):
            payload = await self._get_json(
                f"/execution/{execution_id}/results",
                params={
                    "limit": self.settings.dune_page_limit,
                    "offset": offset,
                },
            )
            result = payload.get("result") or {}
            batch = result.get("rows") or []
            if not isinstance(batch, list):
                raise UpstreamError("dune", 0, f"Dune execution {execution_id} returned an unexpected rows payload")

            rows.extend(batch)
            metadata = result.get("metadata") or metadata

            next_offset = payload.get("next_offset") or result.get("next_offset")
            if next_offset is None:
                total_row_count = metadata.get("total_row_count")
                if total_row_count is not None and len(rows) < int(total_row_count) and batch:
                    next_offset = offset + len(batch)
                else:
                    return DuneQueryResult(
                        query_id=int(payload.get("query_id") or 0),
                        rows=rows,
                        pages=page_index + 1,
                        execution_id=execution_id,
                        state=status.get("state"),
                        submitted_at=status.get("submitted_at"),
                        expires_at=status.get("expires_at"),
                        metadata=metadata,
                    )

            next_offset = int(next_offset)
            if next_offset in seen_offsets or next_offset == offset:
                return DuneQueryResult(
                    query_id=int(payload.get("query_id") or 0),
                    rows=rows,
                    pages=page_index + 1,
                    execution_id=execution_id,
                    state=status.get("state"),
                    submitted_at=status.get("submitted_at"),
                    expires_at=status.get("expires_at"),
                    metadata=metadata,
                )
            seen_offsets.add(offset)
            offset = next_offset

        raise UpstreamError(
            "dune",
            0,
            f"Dune execution {execution_id} exceeded local pagination limit of {self.settings.dune_max_pages} pages",
        )

    async def _wait_for_execution(self, execution_id: str) -> dict[str, Any]:
        for attempt in range(self.settings.dune_sql_max_polls):
            payload = await self._get_json(f"/execution/{execution_id}/status", params={})
            state = str(payload.get("state") or "")
            if state == "QUERY_STATE_COMPLETED":
                return payload
            if state in {"QUERY_STATE_FAILED", "QUERY_STATE_CANCELLED", "QUERY_STATE_EXPIRED"}:
                raise UpstreamError("dune", 0, f"Dune SQL execution {execution_id} ended with {state}")
            if attempt + 1 < self.settings.dune_sql_max_polls:
                await asyncio.sleep(self.settings.dune_sql_poll_interval_seconds)

        raise UpstreamError("dune", 0, f"Dune SQL execution {execution_id} did not complete before local timeout")

    async def _post_json(self, path: str, *, json_payload: dict[str, Any]) -> dict[str, Any]:
        for attempt in range(1, 7):
            try:
                response = await self.client.post(path, json=json_payload)
                if response.status_code in {429, 500, 502, 503, 504} and attempt < 6:
                    await asyncio.sleep(self._backoff_delay(attempt))
                    continue
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict):
                    raise UpstreamError("dune", 0, "Dune returned an unexpected non-object JSON response")
                return payload
            except httpx.HTTPStatusError as exc:
                raise UpstreamError(
                    "dune",
                    exc.response.status_code,
                    f"Dune returned {exc.response.status_code} for {path}: {exc.response.text}",
                ) from exc
            except httpx.HTTPError as exc:
                if attempt < 6:
                    await asyncio.sleep(self._backoff_delay(attempt))
                    continue
                raise UpstreamError("dune", 0, f"Dune request failed for {path}") from exc

        raise UpstreamError("dune", 0, f"Dune request failed for {path}")

    async def _get_json(self, path: str, *, params: dict[str, Any]) -> dict[str, Any]:
        for attempt in range(1, 7):
            try:
                response = await self.client.get(path, params=params)
                if response.status_code in {429, 500, 502, 503, 504} and attempt < 6:
                    await asyncio.sleep(self._backoff_delay(attempt))
                    continue
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict):
                    raise UpstreamError("dune", 0, "Dune returned an unexpected non-object JSON response")
                return payload
            except httpx.HTTPStatusError as exc:
                raise UpstreamError(
                    "dune",
                    exc.response.status_code,
                    f"Dune returned {exc.response.status_code} for {path}",
                ) from exc
            except httpx.HTTPError as exc:
                if attempt < 6:
                    await asyncio.sleep(self._backoff_delay(attempt))
                    continue
                raise UpstreamError("dune", 0, f"Dune request failed for {path}") from exc

        raise UpstreamError("dune", 0, f"Dune request failed for {path}")

    def _backoff_delay(self, attempt: int) -> float:
        return min(8.0, (0.4 * (2 ** (attempt - 1))) + random.uniform(0.1, 0.35))
