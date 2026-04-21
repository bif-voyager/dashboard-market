from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.clients.dune import DuneClient
from app.config import Settings, get_settings
from app.db.database import Database
from app.routes.api import router
from app.services.dashboard import DashboardService
from app.services.repository import Repository
from app.services.sync import SyncService
from app.state import AppServices


async def periodic_sync(sync_service: SyncService, settings: Settings) -> None:
    while True:
        await asyncio.sleep(settings.sync_periodic_interval_seconds)
        await sync_service.run_sync("recent")


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app import state

    settings = get_settings()
    database = Database(settings.sqlite_path)
    repository = Repository(database)
    repository.mark_running_syncs_interrupted()
    dune = DuneClient(settings)
    sync_service = SyncService(settings, repository, dune)
    state.services = AppServices(
        settings=settings,
        database=database,
        repository=repository,
        dashboard=DashboardService(settings, repository),
        sync=sync_service,
        dune=dune,
    )
    background_tasks: list[asyncio.Task] = []
    if settings.sync_on_startup:
        background_tasks.append(asyncio.create_task(sync_service.run_sync(settings.sync_start_scope)))
    if settings.sync_periodic_enabled and settings.sync_periodic_interval_seconds > 0:
        background_tasks.append(asyncio.create_task(periodic_sync(sync_service, settings)))
    try:
        yield
    finally:
        for task in background_tasks:
            task.cancel()
        for task in background_tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
        await dune.close()
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
