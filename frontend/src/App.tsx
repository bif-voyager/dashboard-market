import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { MetricCard } from "./components/MetricCard";
import { NotificationCenter, type NotificationItem } from "./components/NotificationCenter";
import { StatusBanner } from "./components/StatusBanner";
import { StatePanel } from "./components/StatePanel";
import { VolumeChart, type ChartMode } from "./components/VolumeChart";
import {
  buildCsvUrl,
  type CategoryScope,
  fetchCategories,
  fetchVolume,
  syncData,
  type PlatformDataQuality,
  type RangeValue,
} from "./lib/api";
import { formatCurrency } from "./lib/format";
import {
  localeByLanguage,
  translations,
  translateCategory,
  translateCoverage,
  translateDataQualityText,
  type Language,
} from "./lib/i18n";

const rangeOptions: { value: RangeValue; labelKey?: "allTime"; fallback: string }[] = [
  { value: "7d", fallback: "7D" },
  { value: "30d", fallback: "30D" },
  { value: "90d", fallback: "90D" },
  { value: "all", labelKey: "allTime", fallback: "All time" },
];

const categoryScopeOptions: { value: CategoryScope; labelKey: "applyBoth" | "applyPolymarket" | "applyKalshi" }[] = [
  { value: "both", labelKey: "applyBoth" },
  { value: "polymarket", labelKey: "applyPolymarket" },
  { value: "kalshi", labelKey: "applyKalshi" },
];

const chartModeOptions: { value: ChartMode; labelKey: "chartLine" | "chartArea" | "chartBars" | "chartStacked" }[] = [
  { value: "line", labelKey: "chartLine" },
  { value: "area", labelKey: "chartArea" },
  { value: "bar", labelKey: "chartBars" },
  { value: "stacked", labelKey: "chartStacked" },
];

type Theme = "light" | "dark";

function getInitialTheme(): Theme {
  try {
    const savedTheme = window.localStorage.getItem("market-dashboard-theme");
    if (savedTheme === "light" || savedTheme === "dark") {
      return savedTheme;
    }
  } catch {
    return "light";
  }
  return "light";
}

function App() {
  const queryClient = useQueryClient();
  const [range, setRange] = useState<RangeValue>("30d");
  const [selectedCategories, setSelectedCategories] = useState<string[] | null>(null);
  const [categoryScope, setCategoryScope] = useState<CategoryScope>("both");
  const [language, setLanguage] = useState<Language>("en");
  const [theme, setTheme] = useState<Theme>(getInitialTheme);
  const [mobileControlsHidden, setMobileControlsHidden] = useState(false);
  const [categoriesOpen, setCategoriesOpen] = useState(true);
  const [visiblePlatforms, setVisiblePlatforms] = useState({
    polymarket: true,
    kalshi: true,
  });
  const [chartMode, setChartMode] = useState<ChartMode>("line");
  const t = translations[language];
  const locale = localeByLanguage[language];

  const categoriesQuery = useQuery({
    queryKey: ["categories"],
    queryFn: fetchCategories,
  });

  useEffect(() => {
    if (!categoriesQuery.data) {
      return;
    }
    const availableSlugs = categoriesQuery.data.map((item) => item.slug);
    if (selectedCategories === null) {
      setSelectedCategories(availableSlugs);
      return;
    }
    const normalizedSelection = selectedCategories.filter((item) => availableSlugs.includes(item));
    if (normalizedSelection.length !== selectedCategories.length) {
      setSelectedCategories(normalizedSelection.length > 0 ? normalizedSelection : availableSlugs);
    }
  }, [categoriesQuery.data, selectedCategories]);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try {
      window.localStorage.setItem("market-dashboard-theme", theme);
    } catch {
      // Theme persistence is optional; the toggle should still work without storage access.
    }
  }, [theme]);

  useEffect(() => {
    const mobileQuery = window.matchMedia("(max-width: 720px)");
    let lastScrollY = window.scrollY;
    let ticking = false;

    function updateControlsVisibility() {
      ticking = false;
      if (!mobileQuery.matches) {
        setMobileControlsHidden(false);
        lastScrollY = window.scrollY;
        return;
      }

      const currentScrollY = window.scrollY;
      const delta = currentScrollY - lastScrollY;
      if (currentScrollY < 48 || delta < -10) {
        setMobileControlsHidden(false);
      } else if (currentScrollY > 120 && delta > 10) {
        setMobileControlsHidden(true);
      }
      lastScrollY = currentScrollY;
    }

    function requestVisibilityUpdate() {
      if (ticking) {
        return;
      }
      ticking = true;
      window.requestAnimationFrame(updateControlsVisibility);
    }

    window.addEventListener("scroll", requestVisibilityUpdate, { passive: true });
    mobileQuery.addEventListener("change", updateControlsVisibility);
    updateControlsVisibility();
    return () => {
      window.removeEventListener("scroll", requestVisibilityUpdate);
      mobileQuery.removeEventListener("change", updateControlsVisibility);
    };
  }, []);

  const volumeQuery = useQuery({
    queryKey: ["volume", range, selectedCategories, categoryScope],
    queryFn: () => fetchVolume(range, selectedCategories ?? [], categoryScope),
    enabled: selectedCategories !== null && selectedCategories.length > 0,
    placeholderData: (previous) => previous,
    refetchInterval: 300_000,
    refetchIntervalInBackground: false,
  });

  const syncMutation = useMutation({
    mutationFn: ({ scope, platform }: { scope: "recent" | "all"; platform?: "polymarket" | "kalshi" }) =>
      syncData(scope, platform),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["categories"] });
      await queryClient.invalidateQueries({ queryKey: ["volume"] });
    },
  });

  const categories = categoriesQuery.data ?? [];
  const selected = selectedCategories ?? [];
  const allCategoriesSelected = categories.length > 0 && selected.length === categories.length;
  const hasSelection = selectedCategories !== null && selected.length > 0;
  const volume = volumeQuery.data;
  const quality = volume?.dataQuality;
  const hasNonZeroPoints = Boolean(
    volume?.points.some((point) => {
      const polymarketValue = visiblePlatforms.polymarket ? (point.polymarket ?? 0) : 0;
      const kalshiValue = visiblePlatforms.kalshi ? (point.kalshi ?? 0) : 0;
      return polymarketValue + kalshiValue > 0;
    }),
  );
  const initialLoading = categoriesQuery.isLoading || selectedCategories === null;
  const hardError = categoriesQuery.error ?? (!volume && volumeQuery.error ? volumeQuery.error : null);
  const dataQualityNotification =
    volume?.partial || (volume?.warnings ?? []).length > 0
      ? { id: "data-quality", kind: "info" as const, message: t.dataQualityNotice }
      : null;
  const statusNotification = hardError
    ? {
        id: "hard-error",
        kind: "error" as const,
        message: hardError instanceof Error ? hardError.message : t.failedToLoad,
      }
    : volume?.stale
      ? { id: "stale", kind: "warning" as const, message: t.showingCachedData }
      : syncMutation.data?.status === "busy"
        ? { id: "sync-busy", kind: "info" as const, message: t.syncAlreadyRunning }
        : syncMutation.data?.status === "completed"
          ? { id: "sync-completed", kind: "info" as const, message: t.latestSyncFinished }
          : null;
  const notifications: NotificationItem[] = [
    dataQualityNotification,
    statusNotification,
  ].filter((item): item is NotificationItem => item !== null);

  function formatCoverage(qualityItem: PlatformDataQuality | undefined): string {
    return translateCoverage(qualityItem?.coverage, language);
  }

  function toggleCategory(slug: string) {
    if (selectedCategories === null) {
      return;
    }
    if (allCategoriesSelected) {
      setSelectedCategories([slug]);
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

  function toggleAllCategories() {
    if (allCategoriesSelected) {
      setSelectedCategories([]);
      return;
    }
    selectAllCategories();
  }

  function toggleTheme() {
    setTheme((current) => (current === "dark" ? "light" : "dark"));
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
      <div className={mobileControlsHidden ? "floating-controls floating-controls--mobile-hidden" : "floating-controls"}>
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
        <button
          className={theme === "dark" ? "theme-toggle theme-toggle--active" : "theme-toggle"}
          type="button"
          onClick={toggleTheme}
          aria-label={theme === "dark" ? t.lightTheme : t.darkTheme}
          title={theme === "dark" ? t.lightTheme : t.darkTheme}
        >
          <svg viewBox="0 0 24 24" aria-hidden="true" className="theme-toggle__icon">
            <path d="M20.2 15.3A8.4 8.4 0 0 1 8.7 3.8a8.7 8.7 0 1 0 11.5 11.5Z" />
          </svg>
        </button>
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
            onClick={() =>
              syncMutation.mutate(
                range === "all"
                  ? { scope: "all" }
                  : { scope: "recent" },
              )
            }
            disabled={syncMutation.isPending}
          >
            {syncMutation.isPending ? t.syncing : t.refreshData}
          </button>
          <a
            className="action-button action-button--ghost"
            href={buildCsvUrl(range, selected, categoryScope)}
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
            <button className="mini-button" onClick={toggleAllCategories} disabled={!categories.length}>
              {allCategoriesSelected ? t.clearAll : t.selectAll}
            </button>
          </div>
          <div className="filter-scope-row" aria-label={t.filterAppliesTo}>
            <span>{t.filterAppliesTo}</span>
            <div className="scope-pill-row">
              {categoryScopeOptions.map((item) => (
                <button
                  key={item.value}
                  className={item.value === categoryScope ? "scope-pill scope-pill--active" : "scope-pill"}
                  type="button"
                  onClick={() => setCategoryScope(item.value)}
                  aria-pressed={item.value === categoryScope}
                >
                  {t[item.labelKey]}
                </button>
              ))}
            </div>
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

      {!initialLoading && hardError ? (
        <StatePanel
          title={t.failedToLoad}
          body={hardError instanceof Error ? hardError.message : t.failedToLoad}
          action={
            <button
              className="action-button"
              onClick={() => {
                void categoriesQuery.refetch();
                void volumeQuery.refetch();
              }}
            >
              {t.refreshData}
            </button>
          }
        />
      ) : null}

      {!initialLoading && !hardError && hasSelection && volume ? (
        <>
          {volume.stale ? (
            <StatusBanner kind="warning">{t.showingCachedData}</StatusBanner>
          ) : null}

          <section className="metrics-grid">
            <MetricCard
              title={t.polymarketVolume}
              value={formatCurrency(volume.totals.polymarket, locale)}
              tone="sea"
              badge={formatCoverage(quality?.polymarket)}
              detail={translateDataQualityText(quality?.polymarket?.sourceLabel, language)}
            />
            <MetricCard
              title={t.kalshiVolume}
              value={formatCurrency(volume.totals.kalshi, locale)}
              tone="ember"
              badge={formatCoverage(quality?.kalshi)}
              detail={translateDataQualityText(quality?.kalshi?.sourceLabel, language)}
            />
            <MetricCard
              title={t.difference}
              value={formatCurrency(volume.totals.difference, locale)}
              tone="ink"
              detail={translateDataQualityText("Computed from the currently displayed platform totals.", language)}
            />
          </section>

          <section className="chart-card">
            <div className="chart-card__header">
              <div>
                <span className="eyebrow">{t.combinedView}</span>
                <h2>{t.chartTitle}</h2>
              </div>
              <div className="chart-control-stack">
                <div className="chart-mode-row" aria-label={t.chartType}>
                  {chartModeOptions.map((item) => (
                    <button
                      key={item.value}
                      className={item.value === chartMode ? "chart-mode-pill chart-mode-pill--active" : "chart-mode-pill"}
                      type="button"
                      onClick={() => setChartMode(item.value)}
                      aria-pressed={item.value === chartMode}
                    >
                      {t[item.labelKey]}
                    </button>
                  ))}
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
            </div>

            {volumeQuery.isFetching && !volumeQuery.isLoading ? (
              <div className="chart-subtle-note">{t.refreshingChart}</div>
            ) : null}

            {volume.partial ? (
              <div className="chart-data-note">{t.chartDataNote}</div>
            ) : null}

            {hasNonZeroPoints ? (
              <VolumeChart
                data={volume.points}
                visiblePlatforms={visiblePlatforms}
                language={language}
                chartMode={chartMode}
              />
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
