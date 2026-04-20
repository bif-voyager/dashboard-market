import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { MetricCard } from "./components/MetricCard";
import { NotificationCenter, type NotificationItem } from "./components/NotificationCenter";
import { StatePanel } from "./components/StatePanel";
import { VolumeChart } from "./components/VolumeChart";
import { buildCsvUrl, fetchCategories, fetchVolume, syncData, type RangeValue } from "./lib/api";
import { formatCurrency } from "./lib/format";
import {
  localeByLanguage,
  translations,
  translateCategory,
  translateWarning,
  type Language,
} from "./lib/i18n";

const rangeOptions: { value: RangeValue; labelKey?: "allTime"; fallback: string }[] = [
  { value: "7d", fallback: "7D" },
  { value: "30d", fallback: "30D" },
  { value: "90d", fallback: "90D" },
  { value: "all", labelKey: "allTime", fallback: "All time" },
];

function App() {
  const queryClient = useQueryClient();
  const [range, setRange] = useState<RangeValue>("30d");
  const [selectedCategories, setSelectedCategories] = useState<string[] | null>(null);
  const [language, setLanguage] = useState<Language>("en");
  const [categoriesOpen, setCategoriesOpen] = useState(false);
  const [visiblePlatforms, setVisiblePlatforms] = useState({
    polymarket: true,
    kalshi: true,
  });
  const t = translations[language];
  const locale = localeByLanguage[language];

  const categoriesQuery = useQuery({
    queryKey: ["categories"],
    queryFn: fetchCategories,
  });

  useEffect(() => {
    if (!categoriesQuery.data || selectedCategories !== null) {
      return;
    }
    setSelectedCategories(categoriesQuery.data.map((item) => item.slug));
  }, [categoriesQuery.data, selectedCategories]);

  const volumeQuery = useQuery({
    queryKey: ["volume", range, selectedCategories],
    queryFn: () => fetchVolume(range, selectedCategories ?? []),
    enabled: selectedCategories !== null && selectedCategories.length > 0,
    placeholderData: (previous) => previous,
  });

  const syncMutation = useMutation({
    mutationFn: syncData,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["categories"] });
      await queryClient.invalidateQueries({ queryKey: ["volume"] });
    },
  });

  const categories = categoriesQuery.data ?? [];
  const selected = selectedCategories ?? [];
  const hasSelection = selectedCategories !== null && selected.length > 0;
  const volume = volumeQuery.data;
  const hasNonZeroPoints = Boolean(
    volume?.points.some((point) => {
      const polymarketValue = visiblePlatforms.polymarket ? (point.polymarket ?? 0) : 0;
      const kalshiValue = visiblePlatforms.kalshi ? point.kalshi : 0;
      return polymarketValue + kalshiValue > 0;
    }),
  );
  const initialLoading = categoriesQuery.isLoading || selectedCategories === null;
  const hardError = categoriesQuery.error ?? (!volume && volumeQuery.error ? volumeQuery.error : null);
  const notifications: NotificationItem[] = [
    ...(syncMutation.data?.status === "completed"
      ? [{ id: "sync-completed", kind: "info" as const, message: t.latestSyncFinished }]
      : []),
    ...(syncMutation.data?.status === "busy"
      ? [{ id: "sync-busy", kind: "info" as const, message: t.syncAlreadyRunning }]
      : []),
    ...(volume?.stale ? [{ id: "stale", kind: "warning" as const, message: t.showingCachedData }] : []),
    ...(volume?.partial ? [{ id: "partial", kind: "info" as const, message: t.partialHistory }] : []),
    ...((volume?.warnings ?? []).map((warning, index) => ({
      id: `provider-warning-${index}-${warning}`,
      kind: "warning" as const,
      message: translateWarning(warning, language),
    }))),
    ...(hardError
      ? [
          {
            id: "hard-error",
            kind: "error" as const,
            message: hardError instanceof Error ? hardError.message : t.failedToLoad,
          },
        ]
      : []),
  ];

  function toggleCategory(slug: string) {
    if (selectedCategories === null) {
      return;
    }
    if (selectedCategories.includes(slug)) {
      setSelectedCategories(selectedCategories.filter((item) => item !== slug));
      return;
    }
    const next = categories
      .map((item) => item.slug)
      .filter((item) => selectedCategories.includes(item) || item === slug);
    setSelectedCategories(next);
  }

  function selectAllCategories() {
    setSelectedCategories(categories.map((item) => item.slug));
  }

  function togglePlatform(platform: "polymarket" | "kalshi") {
    const otherPlatform = platform === "polymarket" ? "kalshi" : "polymarket";
    if (visiblePlatforms[platform] && !visiblePlatforms[otherPlatform]) {
      return;
    }
    setVisiblePlatforms((current) => ({
      ...current,
      [platform]: !current[platform],
    }));
  }

  return (
    <main className="page-shell">
      <div className="page-shell__glow page-shell__glow--left" />
      <div className="page-shell__glow page-shell__glow--right" />
      <div className="floating-controls">
        <div className="language-toggle" aria-label="Language switcher">
          <button
            className={language === "en" ? "language-option language-option--active" : "language-option"}
            onClick={() => setLanguage("en")}
            type="button"
          >
            EN
          </button>
          <button
            className={language === "ru" ? "language-option language-option--active" : "language-option"}
            onClick={() => setLanguage("ru")}
            type="button"
          >
            RUS
          </button>
        </div>
        <NotificationCenter
          notifications={notifications}
          title={t.notifications}
          emptyLabel={t.noNotifications}
          ariaLabel={t.notificationBell}
          floating
        />
      </div>

      <section className="hero-card">
        <div>
          <span className="eyebrow">{t.eyebrow}</span>
          <h1>{t.title}</h1>
          <p className="hero-copy">
            {t.heroCopy}
          </p>
        </div>

        <div className="hero-actions">
          <button
            className="action-button"
            onClick={() => syncMutation.mutate("recent")}
            disabled={syncMutation.isPending}
          >
            {syncMutation.isPending ? t.syncing : t.refreshData}
          </button>
          <a
            className="action-button action-button--ghost"
            href={buildCsvUrl(range, selected)}
            target="_blank"
            rel="noreferrer"
          >
            {t.exportCsv}
          </a>
        </div>
      </section>

      <section className="toolbar-card">
        <div className="toolbar-row">
          <div>
            <span className="toolbar-label">{t.range}</span>
            <div className="pill-row">
              {rangeOptions.map((item) => (
                <button
                  key={item.value}
                  className={item.value === range ? "pill pill--active" : "pill"}
                  onClick={() => setRange(item.value)}
                >
                  {item.labelKey ? t[item.labelKey] : item.fallback}
                </button>
              ))}
            </div>
          </div>

          <span className="toolbar-date-spacer" aria-hidden="true" />
        </div>

        <div className="category-section">
          <div className="toolbar-chip-header">
            <button
              className={categoriesOpen ? "category-toggle category-toggle--active" : "category-toggle"}
              type="button"
              onClick={() => setCategoriesOpen((current) => !current)}
              aria-expanded={categoriesOpen}
            >
              <span>{t.categories}</span>
              <strong>{selected.length}</strong>
            </button>
            <button className="mini-button" onClick={selectAllCategories} disabled={!categories.length}>
              {t.selectAll}
            </button>
          </div>
          {categoriesOpen ? (
            <div className="chip-grid">
              {categories.map((item) => {
                const active = selected.includes(item.slug);
                return (
                  <button
                    key={item.slug}
                    className={active ? "chip chip--active" : "chip"}
                    onClick={() => toggleCategory(item.slug)}
                  >
                    <span>{translateCategory(item.slug, item.label, language)}</span>
                    <small>{item.platforms.join(" + ")}</small>
                  </button>
                );
              })}
            </div>
          ) : null}
        </div>
      </section>

      {initialLoading ? (
        <section className="loading-grid">
          <div className="loading-card" />
          <div className="loading-card" />
          <div className="loading-card" />
          <div className="loading-chart" />
        </section>
      ) : null}

      {!initialLoading && hasSelection && volume ? (
        <>
          <section className="metrics-grid">
            <MetricCard title={t.polymarketVolume} value={formatCurrency(volume.totals.polymarket, locale)} tone="sea" />
            <MetricCard title={t.kalshiVolume} value={formatCurrency(volume.totals.kalshi, locale)} tone="ember" />
            <MetricCard title={t.difference} value={formatCurrency(volume.totals.difference, locale)} tone="ink" />
          </section>

          <section className="chart-card">
            <div className="chart-card__header">
              <div>
                <span className="eyebrow">{t.combinedView}</span>
                <h2>{t.chartTitle}</h2>
              </div>
              <div className="legend-row">
                <button
                  className={visiblePlatforms.polymarket ? "legend-chip legend-chip--sea" : "legend-chip legend-chip--muted"}
                  onClick={() => togglePlatform("polymarket")}
                  aria-pressed={visiblePlatforms.polymarket}
                  type="button"
                >
                  Polymarket
                </button>
                <button
                  className={visiblePlatforms.kalshi ? "legend-chip legend-chip--ember" : "legend-chip legend-chip--muted"}
                  onClick={() => togglePlatform("kalshi")}
                  aria-pressed={visiblePlatforms.kalshi}
                  type="button"
                >
                  Kalshi
                </button>
              </div>
            </div>

            {volumeQuery.isFetching && !volumeQuery.isLoading ? (
              <div className="chart-subtle-note">{t.refreshingChart}</div>
            ) : null}

            {hasNonZeroPoints ? (
              <VolumeChart data={volume.points} visiblePlatforms={visiblePlatforms} language={language} />
            ) : (
              <StatePanel
                title={t.noVolumeTitle}
                body={t.noVolumeBody}
              />
            )}
          </section>
        </>
      ) : null}

      {!initialLoading && selectedCategories !== null && selectedCategories.length === 0 ? (
        <StatePanel
          title={t.chooseCategoryTitle}
          body={t.chooseCategoryBody}
          action={
            <button className="action-button" onClick={selectAllCategories}>
              {t.restoreFilters}
            </button>
          }
        />
      ) : null}
    </main>
  );
}

export default App;
