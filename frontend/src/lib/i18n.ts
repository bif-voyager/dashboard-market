export type Language = "en" | "ru";

export const localeByLanguage: Record<Language, string> = {
  en: "en-US",
  ru: "ru-RU",
};

export const translations = {
  en: {
    eyebrow: "Hiring-test ready dashboard",
    title: "Historical market volume across Polymarket and Kalshi",
    heroCopy:
      "Read-only analytics on top of public market-data APIs, normalized into one UTC daily market-volume view.",
    refreshData: "Refresh data",
    syncing: "Syncing...",
    exportCsv: "Export CSV",
    latestSyncFinished: "Latest sync finished. Queries were refreshed against the local cache.",
    syncAlreadyRunning:
      "A sync is already running in the backend. The dashboard will refresh once that in-flight job updates the cache.",
    showingCachedData: "Showing cached data. One of the upstream syncs last failed, so the chart may be partially stale.",
    partialHistory:
      "Some source history is partial. The chart uses the local cache plus any provider metadata that is safe to apply.",
    failedToLoad: "Failed to load dashboard data.",
    range: "Range",
    allTime: "All time",
    asOf: "As of",
    categories: "Categories",
    selectAll: "Select all",
    polymarketVolume: "Polymarket volume",
    kalshiVolume: "Kalshi volume",
    difference: "Difference",
    combinedView: "Combined view",
    chartTitle: "Daily market volume in USD notional",
    refreshingChart: "Refreshing chart with cached data kept in place.",
    noVolumeTitle: "No volume found",
    noVolumeBody:
      "There is no materialized market volume for the chosen categories and visible platforms in this range yet.",
    chooseCategoryTitle: "Choose at least one category",
    chooseCategoryBody: "The chart is intentionally empty until you select one or more categories.",
    restoreFilters: "Restore filters",
    noData: "No data",
    noSyncedData: "No synced data yet",
    notifications: "Notifications",
    noNotifications: "No notifications yet",
    notificationBell: "Open notifications",
  },
  ru: {
    eyebrow: "Дашборд для тестового задания",
    title: "Исторический объём рынков Polymarket и Kalshi",
    heroCopy:
      "Аналитика только для чтения на публичных API рыночных данных, нормализованная в дневной UTC-график объёма рынка.",
    refreshData: "Обновить данные",
    syncing: "Синхронизация...",
    exportCsv: "Экспорт CSV",
    latestSyncFinished: "Последняя синхронизация завершена. Запросы обновлены из локального кэша.",
    syncAlreadyRunning:
      "Синхронизация уже идёт на бэкенде. Дашборд обновится, когда текущая задача запишет кэш.",
    showingCachedData:
      "Показаны кэшированные данные. Одна из синхронизаций с внешними источниками недавно завершилась с ошибкой, поэтому график может быть частично устаревшим.",
    partialHistory:
      "Часть истории неполная. График использует локальный кэш и безопасно применимые метаданные провайдеров.",
    failedToLoad: "Не удалось загрузить данные дашборда.",
    range: "Диапазон",
    allTime: "Всё время",
    asOf: "На дату",
    categories: "Категории",
    selectAll: "Выбрать всё",
    polymarketVolume: "Объём Polymarket",
    kalshiVolume: "Объём Kalshi",
    difference: "Разница",
    combinedView: "Общий график",
    chartTitle: "Дневной объём рынка в долларовом выражении",
    refreshingChart: "График обновляется, кэшированные данные пока остаются на экране.",
    noVolumeTitle: "Объём не найден",
    noVolumeBody:
      "Для выбранных категорий и видимых платформ в этом диапазоне пока нет материализованного объёма.",
    chooseCategoryTitle: "Выберите хотя бы одну категорию",
    chooseCategoryBody: "График специально пустой, пока не выбрана одна или несколько категорий.",
    restoreFilters: "Вернуть фильтры",
    noData: "Нет данных",
    noSyncedData: "Данных синхронизации пока нет",
    notifications: "Уведомления",
    noNotifications: "Уведомлений пока нет",
    notificationBell: "Открыть уведомления",
  },
} satisfies Record<Language, Record<string, string>>;

const categoryLabelsRu: Record<string, string> = {
  "climate-and-weather": "Климат и погода",
  commodities: "Сырьевые товары",
  companies: "Компании",
  crypto: "Крипто",
  economics: "Экономика",
  entertainment: "Развлечения",
  finance: "Финансы",
  health: "Здоровье",
  mentions: "Упоминания",
  politics: "Политика",
  "science-and-technology": "Наука и технологии",
  social: "Социальное",
  sports: "Спорт",
  uncategorized: "Без категории",
  world: "Мир",
};

export function translateCategory(slug: string, fallback: string, language: Language): string {
  if (language === "en") {
    return fallback;
  }
  return categoryLabelsRu[slug] ?? fallback;
}

export function translateWarning(message: string, language: Language): string {
  if (language === "en") {
    return message;
  }

  if (message.includes("current UTC day is excluded")) {
    return "Текущий UTC-день исключён из графика, потому что публичные дневные API-методы могут быть неполными до закрытия дня.";
  }
  if (message.includes("Polymarket chart uses the public builder-volume daily series")) {
    return "График Polymarket использует публичную дневную серию объёма builder-volume как платформенную оценку; сырые сделки нужны только для диагностики.";
  }
  if (message.includes("Polymarket category filters are estimated")) {
    return "Фильтры категорий Polymarket являются оценкой: публичная дневная серия объёма builder-volume масштабируется по доле выбранных категорий в метаданных.";
  }
  if (message.includes("Polymarket has no materialized daily data")) {
    return "Для выбранных категорий Polymarket нет материализованных дневных данных в этом диапазоне.";
  }
  if (message.includes("Kalshi daily series is derived from public candlestick volume")) {
    return "Дневная серия Kalshi построена из публичного объёма дневных свечей по материализованному реестру рынков.";
  }
  if (message.includes("Kalshi totals are materialized from the current registry subset")) {
    return "Итоги Kalshi материализованы из текущей части реестра; пагинация прямого списка рынков не исчерпала все открытые и закрытые рынки.";
  }

  return message;
}
