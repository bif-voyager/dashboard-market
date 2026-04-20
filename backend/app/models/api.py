from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


RangeValue = Literal["7d", "30d", "90d", "all"]
SyncScope = Literal["recent", "all"]
SourceType = Literal["exact", "derived", "proxy", "estimated"]
CoverageType = Literal["full", "partial", "unknown"]


class CategoryItem(BaseModel):
    slug: str
    label: str
    platforms: list[str] = Field(default_factory=list)


class SyncSnapshot(BaseModel):
    platform: str
    scope: str
    status: str
    startedAt: str | None = None
    finishedAt: str | None = None
    partial: bool = False
    message: str | None = None
    stats: dict = Field(default_factory=dict)


class HealthResponse(BaseModel):
    ok: bool
    asOf: str | None = None
    stats: dict[str, int | str | None]
    sync: list[SyncSnapshot]


class VolumePoint(BaseModel):
    date: str
    polymarket: float | None = None
    kalshi: float | None = None
    total: float


class VolumeTotals(BaseModel):
    polymarket: float
    kalshi: float
    difference: float
    total: float


class PlatformDataQuality(BaseModel):
    dailySeries: str
    sourceType: SourceType
    sourceLabel: str
    categoryFilter: str
    exact: bool = False
    isEstimated: bool = False
    partial: bool = False
    coverage: CoverageType = "unknown"
    coverageReason: str | None = None
    rawTrades: str | None = None


class VolumeResponse(BaseModel):
    range: RangeValue
    categories: list[str]
    timezone: str
    asOf: str | None = None
    partial: bool = False
    stale: bool = False
    warnings: list[str] = Field(default_factory=list)
    dataQuality: dict[str, PlatformDataQuality] = Field(default_factory=dict)
    totals: VolumeTotals
    points: list[VolumePoint]


class SyncResponse(BaseModel):
    scope: SyncScope
    platform: str | None = None
    status: str
    partial: bool = False
    results: dict[str, dict]
