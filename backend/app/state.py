from __future__ import annotations

from dataclasses import dataclass

from app.clients.kalshi import KalshiAdapter
from app.clients.polymarket import PolymarketAdapter
from app.config import Settings
from app.db.database import Database
from app.services.dashboard import DashboardService
from app.services.repository import Repository
from app.services.sync import SyncService


@dataclass(slots=True)
class AppServices:
    settings: Settings
    database: Database
    repository: Repository
    dashboard: DashboardService
    sync: SyncService
    polymarket: PolymarketAdapter
    kalshi: KalshiAdapter


services: AppServices | None = None
