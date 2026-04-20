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
    chartDataNote: "Some history may be incomplete because of public API limits.",
    dataQualityNotice:
      "Data is partially incomplete. Polymarket uses a public approximate daily series, while Kalshi uses public daily candlesticks.",
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
    darkTheme: "Turn on dark theme",
    lightTheme: "Turn on light theme",
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
    chartDataNote: "Часть истории может быть неполной из-за ограничений публичных API.",
    dataQualityNotice:
      "Данные частично неполные. Polymarket показан по публичной ориентировочной дневной серии, Kalshi — по публичным дневным свечам.",
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
    darkTheme: "Включить тёмную тему",
    lightTheme: "Включить светлую тему",
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

const coverageLabelsRu: Record<string, string> = {
  full: "ПОЛНО",
  partial: "НЕПОЛНО",
  unknown: "НЕЯСНО",
};

const dataQualityTextRu: Record<string, string> = {
  "Polymarket public builder-volume proxy scaled by category metadata share":
    "Ориентировочный объём Polymarket, пересчитанный по доле выбранных категорий",
  "Public builder analytics do not expose exact exchange-wide daily category history.":
    "Публичная аналитика не даёт точную дневную историю по категориям для всей биржи.",
  "Polymarket public builder-volume platform proxy":
    "Публичный ориентировочный объём Polymarket",
  "Public builder analytics are real data but not guaranteed exchange-wide canonical volume.":
    "Публичная аналитика основана на реальных данных, но не гарантирует точный общий объём всей биржи.",
  "Polymarket sampled-trade aggregation from discovered event and market candidates":
    "Сумма найденных сделок Polymarket по выбранным событиям и рынкам",
  "Raw trades are synced from capped event and market samples rather than a full exchange-wide backfill.":
    "Сырые сделки загружаются из ограниченной выборки событий и рынков, а не из полной истории всей биржи.",
  "Kalshi recent candlestick rows extended backward by capped raw public trade backfill":
    "Свежие свечи Kalshi, дополненные назад ограниченной загрузкой публичных сделок",
  "Recent rows come from public market candlesticks; older rows are added from raw public trades over the Kalshi backfill window. ":
    "Свежие дни берутся из публичных рыночных свечей; более старые дни добавлены из публичных сделок Kalshi за доступный период дозагрузки. ",
  "Heavy historical days are capped by page budget, so these older rows are not canonical full-day totals.":
    "Дни с большим числом сделок ограничены лимитом загрузки, поэтому старые значения не являются точными итогами за полный день.",
  "Kalshi materialized cache mixing recent candlestick rows with older cached history":
    "Локальное хранилище Kalshi: свежие свечи вместе с ранее сохранённой старой историей",
  "Recent rows come from public candlesticks; older rows only exist if they were previously materialized into the local cache.":
    "Свежие дни берутся из публичных свечей; старые дни есть только если раньше были сохранены в локальное хранилище.",
  "Kalshi public candlestick-derived daily series":
    "Дневной ряд Kalshi, рассчитанный по публичным свечам",
  "Recent rows are aggregated from public market candlesticks over the discovered ticker universe.":
    "Свежие дни собраны из публичных рыночных свечей по найденным обозначениям рынков.",
  " Coverage is partial because market discovery or candle fetches hit public API limits.":
    " Покрытие неполное, потому что поиск рынков или загрузка свечей упёрлись в лимиты публичного доступа к данным.",
  "Computed from the currently displayed platform totals.":
    "Рассчитано по текущим отображаемым итогам платформ.",
};

export function translateCoverage(coverage: string | undefined, language: Language): string {
  const safeCoverage = coverage ?? "unknown";
  if (language === "en") {
    return safeCoverage.toUpperCase();
  }
  return coverageLabelsRu[safeCoverage] ?? safeCoverage.toUpperCase();
}

export function translateDataQualityText(message: string | null | undefined, language: Language): string | undefined {
  if (!message) {
    return undefined;
  }
  if (language === "en") {
    return message;
  }

  return Object.entries(dataQualityTextRu).reduce(
    (translated, [source, replacement]) => translated.replaceAll(source, replacement),
    message,
  );
}
