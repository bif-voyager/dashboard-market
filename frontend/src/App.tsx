import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { MetricCard } from "./components/MetricCard";
import { StatePanel } from "./components/StatePanel";
import { StatusBanner } from "./components/StatusBanner";
import { VolumeChart } from "./components/VolumeChart";
import { buildCsvUrl, fetchCategories, fetchVolume, syncData, type RangeValue } from "./lib/api";
import { formatAsOf, formatCurrency } from "./lib/format";

const rangeOptions: { value: RangeValue; label: string }[] = [
  { value: "7d", label: "7D" },
  { value: "30d", label: "30D" },
  { value: "90d", label: "90D" },
  { value: "all", label: "All time" },
];

function App() {
  const queryClient = useQueryClient();
  const [range, setRange] = useState<RangeValue>("30d");
  const [selectedCategories, setSelectedCategories] = useState<string[] | null>(null);
  const [visiblePlatforms, setVisiblePlatforms] = useState({
    polymarket: true,
    kalshi: true,
  });

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

      <section className="hero-card">
        <div>
          <span className="eyebrow">Hiring-test ready dashboard</span>
          <h1>Historical market volume across Polymarket and Kalshi</h1>
          <p className="hero-copy">
            Read-only analytics on top of public market-data APIs, normalized into one UTC daily market-volume view.
          </p>
        </div>

        <div className="hero-actions">
          <button
            className="action-button"
            onClick={() => syncMutation.mutate("recent")}
            disabled={syncMutation.isPending}
          >
            {syncMutation.isPending ? "Syncing..." : "Refresh data"}
          </button>
          <a
            className="action-button action-button--ghost"
            href={buildCsvUrl(range, selected)}
            target="_blank"
            rel="noreferrer"
          >
            Export CSV
          </a>
        </div>
      </section>

      {syncMutation.data?.status === "completed" ? (
        <StatusBanner kind="info">Latest sync finished. Queries were refreshed against the local cache.</StatusBanner>
      ) : null}
      {syncMutation.data?.status === "busy" ? (
        <StatusBanner kind="info">
          A sync is already running in the backend. The dashboard will refresh once that in-flight job updates the cache.
        </StatusBanner>
      ) : null}
      {volume?.stale ? (
        <StatusBanner kind="warning">
          Showing cached data. One of the upstream syncs last failed, so the chart may be partially stale.
        </StatusBanner>
      ) : null}
      {volume?.partial ? (
        <StatusBanner kind="info">
          Some source history is partial. The chart uses the local cache plus any provider metadata that is safe to apply.
        </StatusBanner>
      ) : null}
      {volume?.warnings.map((warning) => (
        <StatusBanner key={warning} kind="warning">
          {warning}
        </StatusBanner>
      ))}
      {hardError ? (
        <StatusBanner kind="error">
          {hardError instanceof Error ? hardError.message : "Failed to load dashboard data."}
        </StatusBanner>
      ) : null}

      <section className="toolbar-card">
        <div className="toolbar-row">
          <div>
            <span className="toolbar-label">Range</span>
            <div className="pill-row">
              {rangeOptions.map((item) => (
                <button
                  key={item.value}
                  className={item.value === range ? "pill pill--active" : "pill"}
                  onClick={() => setRange(item.value)}
                >
                  {item.label}
                </button>
              ))}
            </div>
          </div>

          <div className="toolbar-meta">
            <span className="toolbar-label">As of</span>
            <strong>{formatAsOf(volume?.asOf ?? null)}</strong>
          </div>
        </div>

        <div>
          <div className="toolbar-chip-header">
            <span className="toolbar-label">Categories</span>
            <button className="mini-button" onClick={selectAllCategories} disabled={!categories.length}>
              Select all
            </button>
          </div>
          <div className="chip-grid">
            {categories.map((item) => {
              const active = selected.includes(item.slug);
              return (
                <button
                  key={item.slug}
                  className={active ? "chip chip--active" : "chip"}
                  onClick={() => toggleCategory(item.slug)}
                >
                  <span>{item.label}</span>
                  <small>{item.platforms.join(" + ")}</small>
                </button>
              );
            })}
          </div>
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
            <MetricCard title="Polymarket volume" value={formatCurrency(volume.totals.polymarket)} tone="sea" />
            <MetricCard title="Kalshi volume" value={formatCurrency(volume.totals.kalshi)} tone="ember" />
            <MetricCard title="Difference" value={formatCurrency(volume.totals.difference)} tone="ink" />
          </section>

          <section className="chart-card">
            <div className="chart-card__header">
              <div>
                <span className="eyebrow">Combined view</span>
                <h2>Daily market volume in USD notional</h2>
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
              <div className="chart-subtle-note">Refreshing chart with cached data kept in place.</div>
            ) : null}

            {hasNonZeroPoints ? (
              <VolumeChart data={volume.points} visiblePlatforms={visiblePlatforms} />
            ) : (
              <StatePanel
                title="No volume found"
                body="There is no materialized market volume for the chosen categories and visible platforms in this range yet."
              />
            )}
          </section>
        </>
      ) : null}

      {!initialLoading && selectedCategories !== null && selectedCategories.length === 0 ? (
        <StatePanel
          title="Choose at least one category"
          body="The chart is intentionally empty until you select one or more categories."
          action={
            <button className="action-button" onClick={selectAllCategories}>
              Restore filters
            </button>
          }
        />
      ) : null}
    </main>
  );
}

export default App;
