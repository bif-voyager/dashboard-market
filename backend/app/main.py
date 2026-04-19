from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.clients.kalshi import KalshiAdapter
from app.clients.polymarket import PolymarketAdapter
from app.config import Settings, get_settings
from app.db.database import Database
from app.routes.api import router
from app.services.dashboard import DashboardService
from app.services.repository import Repository
from app.services.sync import SyncService
from app.state import AppServices


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app import state

    settings = get_settings()
    database = Database(settings.sqlite_path)
    repository = Repository(database)
    repository.mark_running_syncs_interrupted()
    polymarket = PolymarketAdapter(settings)
    kalshi = KalshiAdapter(settings)
    sync_service = SyncService(repository, polymarket, kalshi)
    state.services = AppServices(
        settings=settings,
        database=database,
        repository=repository,
        dashboard=DashboardService(repository),
        sync=sync_service,
        polymarket=polymarket,
        kalshi=kalshi,
    )
    if settings.sync_on_startup:
        asyncio.create_task(sync_service.run_sync(settings.sync_start_scope))
    try:
        yield
    finally:
        await polymarket.close()
        await kalshi.close()
        state.services = None


def create_app() -> FastAPI:
    app = FastAPI(title="Market Dashboard API", version="0.1.0", lifespan=lifespan)
    settings = get_settings()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router)
    return app


app = create_app()
