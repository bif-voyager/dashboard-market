from __future__ import annotations

import csv
from io import StringIO

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse

from app.models.api import CategoryItem, HealthResponse, SyncResponse
from app.state import AppServices

router = APIRouter(prefix="/api")


def get_services() -> AppServices:
    from app.state import services

    if services is None:
        raise RuntimeError("Application services are not initialized")
    return services


@router.get("/health", response_model=HealthResponse)
async def health(app_services: AppServices = Depends(get_services)) -> dict:
    stats = app_services.repository.get_stats()
    return {
        "ok": True,
        "asOf": stats.get("latestDay"),
        "stats": stats,
        "sync": app_services.repository.get_sync_states(),
    }


@router.get("/categories", response_model=list[CategoryItem])
async def categories(app_services: AppServices = Depends(get_services)) -> list[dict]:
    return app_services.dashboard.list_categories()


@router.get("/volume")
async def volume(
    range_value: str = Query(default="30d", alias="range"),
    categories: str | None = Query(default=None),
    category_scope: str = Query(default="both", alias="categoryScope"),
    app_services: AppServices = Depends(get_services),
) -> dict:
    if range_value not in {"7d", "30d", "90d", "all"}:
        raise HTTPException(status_code=400, detail="range must be one of 7d, 30d, 90d, all")
    if category_scope not in {"both", "polymarket", "kalshi"}:
        raise HTTPException(status_code=400, detail="categoryScope must be one of both, polymarket, kalshi")
    selected_categories = None
    if categories is not None:
        selected_categories = [item.strip() for item in categories.split(",") if item.strip()]
        if categories == "":
            selected_categories = []
    return app_services.dashboard.build_volume_response(
        range_value=range_value,
        categories=selected_categories,
        category_scope=category_scope,
    )


@router.post("/admin/sync", response_model=SyncResponse)
async def sync(
    scope: str = Query(default="recent"),
    platform: str | None = Query(default=None),
    app_services: AppServices = Depends(get_services),
) -> dict:
    if scope not in {"recent", "all"}:
        raise HTTPException(status_code=400, detail="scope must be recent or all")
    if platform not in {None, "polymarket", "kalshi"}:
        raise HTTPException(status_code=400, detail="platform must be polymarket or kalshi")
    result = await app_services.sync.run_sync(scope, platform=platform)
    return {"scope": scope, "platform": platform, **result}


@router.get("/export.csv", response_class=PlainTextResponse)
async def export_csv(
    range_value: str = Query(default="30d", alias="range"),
    categories: str | None = Query(default=None),
    category_scope: str = Query(default="both", alias="categoryScope"),
    app_services: AppServices = Depends(get_services),
) -> str:
    if not app_services.settings.enable_csv_export:
        raise HTTPException(status_code=404, detail="CSV export is disabled")
    if category_scope not in {"both", "polymarket", "kalshi"}:
        raise HTTPException(status_code=400, detail="categoryScope must be one of both, polymarket, kalshi")
    payload = app_services.dashboard.build_volume_response(
        range_value=range_value,
        categories=None if categories is None else [item.strip() for item in categories.split(",") if item.strip()],
        category_scope=category_scope,
    )
    buffer = StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["date", "platform", "category_scope", "applied_to", "volume_usd_notional"])
    category_scope_label = ",".join(payload["categories"]) if payload["categories"] else "all"
    for point in payload["points"]:
        writer.writerow([point["date"], "polymarket", category_scope_label, payload["categoryScope"], point["polymarket"]])
        writer.writerow([point["date"], "kalshi", category_scope_label, payload["categoryScope"], point["kalshi"]])
    return buffer.getvalue()
