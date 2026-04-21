import { useEffect, useRef, useState, type PointerEvent, type WheelEvent } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  Bar,
  BarChart,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { VolumePoint } from "../lib/api";
import { formatCompactCurrency, formatCurrency, formatDateLabel } from "../lib/format";
import type { Language } from "../lib/i18n";
import { localeByLanguage, translations } from "../lib/i18n";

export type ChartMode = "line" | "area" | "bar" | "stacked";

interface VolumeChartProps {
  data: VolumePoint[];
  visiblePlatforms: {
    polymarket: boolean;
    kalshi: boolean;
  };
  language: Language;
  chartMode: ChartMode;
}

interface WindowRange {
  start: number;
  end: number;
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

function fullWindow(length: number): WindowRange {
  return { start: 0, end: Math.max(length - 1, 0) };
}

export function VolumeChart({ data, visiblePlatforms, language, chartMode }: VolumeChartProps) {
  const locale = localeByLanguage[language];
  const t = translations[language];
  const shellRef = useRef<HTMLDivElement | null>(null);
  const dragStateRef = useRef<{
    pointerId: number;
    lastClientX: number;
    accumulatedPixels: number;
  } | null>(null);
  const [windowRange, setWindowRange] = useState<WindowRange>(() => fullWindow(data.length));
  const [isDragging, setIsDragging] = useState(false);
  const firstDate = data[0]?.date ?? "";
  const lastDate = data[data.length - 1]?.date ?? "";

  useEffect(() => {
    setWindowRange(fullWindow(data.length));
  }, [data.length, firstDate, lastDate]);

  const safeStart = clamp(windowRange.start, 0, Math.max(data.length - 1, 0));
  const safeEnd = clamp(windowRange.end, safeStart, Math.max(data.length - 1, 0));
  const visibleData = data.slice(safeStart, safeEnd + 1);
  const visibleSpan = Math.max(safeEnd - safeStart + 1, 1);
  const minWindowSize = Math.min(Math.max(data.length, 1), 7);

  function resetWindow() {
    setWindowRange(fullWindow(data.length));
  }

  function shiftWindow(shift: number) {
    if (!shift || data.length <= visibleSpan) {
      return;
    }
    setWindowRange((current) => {
      const span = current.end - current.start + 1;
      const nextStart = clamp(current.start + shift, 0, Math.max(data.length - span, 0));
      return { start: nextStart, end: nextStart + span - 1 };
    });
  }

  function zoomWindow(deltaY: number, anchorRatio: number) {
    if (data.length <= minWindowSize) {
      return;
    }
    setWindowRange((current) => {
      const currentSpan = current.end - current.start + 1;
      const zoomFactor = deltaY < 0 ? 0.78 : 1.24;
      const nextSpan = clamp(Math.round(currentSpan * zoomFactor), minWindowSize, data.length);
      const anchorIndex = current.start + anchorRatio * Math.max(currentSpan - 1, 0);
      let nextStart = Math.round(anchorIndex - anchorRatio * Math.max(nextSpan - 1, 0));
      nextStart = clamp(nextStart, 0, Math.max(data.length - nextSpan, 0));
      return { start: nextStart, end: nextStart + nextSpan - 1 };
    });
  }

  function handleWheel(event: WheelEvent<HTMLDivElement>) {
    if (data.length <= minWindowSize) {
      return;
    }
    event.preventDefault();
    const bounds = event.currentTarget.getBoundingClientRect();
    const anchorRatio = bounds.width > 0 ? clamp((event.clientX - bounds.left) / bounds.width, 0, 1) : 0.5;
    zoomWindow(event.deltaY, anchorRatio);
  }

  function handlePointerDown(event: PointerEvent<HTMLDivElement>) {
    if (event.button !== 0 || data.length <= visibleSpan) {
      return;
    }
    dragStateRef.current = {
      pointerId: event.pointerId,
      lastClientX: event.clientX,
      accumulatedPixels: 0,
    };
    event.currentTarget.setPointerCapture(event.pointerId);
    setIsDragging(true);
  }

  function handlePointerMove(event: PointerEvent<HTMLDivElement>) {
    const dragState = dragStateRef.current;
    if (!dragState || dragState.pointerId !== event.pointerId) {
      return;
    }
    const bounds = shellRef.current?.getBoundingClientRect();
    const width = bounds?.width ?? 0;
    if (width <= 0) {
      return;
    }

    const deltaPixels = event.clientX - dragState.lastClientX;
    dragState.lastClientX = event.clientX;
    dragState.accumulatedPixels += deltaPixels;
    const pixelsPerPoint = width / visibleSpan;
    const shift = Math.trunc(-dragState.accumulatedPixels / pixelsPerPoint);
    if (shift !== 0) {
      shiftWindow(shift);
      dragState.accumulatedPixels += shift * pixelsPerPoint;
    }
  }

  function handlePointerUp(event: PointerEvent<HTMLDivElement>) {
    const dragState = dragStateRef.current;
    if (dragState?.pointerId === event.pointerId) {
      dragStateRef.current = null;
      setIsDragging(false);
    }
  }

  const chartDefs = (
    <defs>
      <linearGradient id="seaArea" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stopColor="var(--sea)" stopOpacity={0.34} />
        <stop offset="100%" stopColor="var(--sea)" stopOpacity={0.04} />
      </linearGradient>
      <linearGradient id="emberArea" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stopColor="var(--ember)" stopOpacity={0.32} />
        <stop offset="100%" stopColor="var(--ember)" stopOpacity={0.04} />
      </linearGradient>
    </defs>
  );

  const chartGrid = <CartesianGrid strokeDasharray="3 6" stroke="var(--chart-grid)" vertical={false} />;

  const chartXAxis = (
    <XAxis
      dataKey="date"
      tickFormatter={(value: string) => formatDateLabel(value, locale)}
      tick={{ fill: "var(--chart-tick)", fontSize: 12 }}
      axisLine={false}
      tickLine={false}
      minTickGap={28}
    />
  );

  const chartYAxis = (
    <YAxis
      tickFormatter={(value: number) => formatCompactCurrency(value, locale)}
      tick={{ fill: "var(--chart-tick)", fontSize: 12 }}
      axisLine={false}
      tickLine={false}
      width={86}
    />
  );

  const chartTooltip = (
    <Tooltip
      contentStyle={{
        borderRadius: 18,
        border: "1px solid var(--line)",
        boxShadow: "var(--tooltip-shadow)",
        background: "var(--tooltip-bg)",
        color: "var(--ink)",
      }}
      formatter={(value: unknown, name: string) => [
        typeof value === "number" ? formatCurrency(value, locale) : t.noData,
        name === "polymarket" ? "Polymarket" : "Kalshi",
      ]}
      labelFormatter={(label: string) =>
        new Date(`${label}T00:00:00Z`).toLocaleDateString(locale, {
          weekday: "short",
          month: "short",
          day: "numeric",
          year: "numeric",
        })
      }
    />
  );

  const lineSeries = (
    <>
      <Line
        type="monotone"
        dataKey="polymarket"
        stroke="var(--sea)"
        strokeWidth={3}
        dot={false}
        connectNulls={false}
        hide={!visiblePlatforms.polymarket}
        activeDot={{ r: 5, fill: "var(--sea)" }}
        isAnimationActive={false}
      />
      <Line
        type="monotone"
        dataKey="kalshi"
        stroke="var(--ember)"
        strokeWidth={3}
        dot={false}
        connectNulls={false}
        hide={!visiblePlatforms.kalshi}
        activeDot={{ r: 5, fill: "var(--ember)" }}
        isAnimationActive={false}
      />
    </>
  );

  const areaSeries = (
    <>
      <Area
        type="monotone"
        dataKey="polymarket"
        stroke="var(--sea)"
        fill="url(#seaArea)"
        strokeWidth={2.5}
        dot={false}
        connectNulls={false}
        hide={!visiblePlatforms.polymarket}
        activeDot={{ r: 5, fill: "var(--sea)" }}
        isAnimationActive={false}
      />
      <Area
        type="monotone"
        dataKey="kalshi"
        stroke="var(--ember)"
        fill="url(#emberArea)"
        strokeWidth={2.5}
        dot={false}
        connectNulls={false}
        hide={!visiblePlatforms.kalshi}
        activeDot={{ r: 5, fill: "var(--ember)" }}
        isAnimationActive={false}
      />
    </>
  );

  const barSeries = (
    <>
      <Bar
        dataKey="polymarket"
        fill="var(--sea)"
        radius={[6, 6, 0, 0]}
        maxBarSize={18}
        hide={!visiblePlatforms.polymarket}
        isAnimationActive={false}
      />
      <Bar
        dataKey="kalshi"
        fill="var(--ember)"
        radius={[6, 6, 0, 0]}
        maxBarSize={18}
        hide={!visiblePlatforms.kalshi}
        isAnimationActive={false}
      />
    </>
  );

  const stackedSeries = (
    <>
      <Area
        type="monotone"
        dataKey="polymarket"
        stackId="volume"
        stroke="var(--sea)"
        fill="url(#seaArea)"
        strokeWidth={2}
        dot={false}
        hide={!visiblePlatforms.polymarket}
        isAnimationActive={false}
      />
      <Area
        type="monotone"
        dataKey="kalshi"
        stackId="volume"
        stroke="var(--ember)"
        fill="url(#emberArea)"
        strokeWidth={2}
        dot={false}
        hide={!visiblePlatforms.kalshi}
        isAnimationActive={false}
      />
    </>
  );

  const chartMargin = { top: 20, right: 12, left: 0, bottom: 0 };

  return (
    <div
      ref={shellRef}
      className={isDragging ? "chart-shell chart-shell--dragging" : "chart-shell"}
      onWheel={handleWheel}
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={handlePointerUp}
      onPointerCancel={handlePointerUp}
      onDoubleClick={resetWindow}
      role="application"
      aria-label={t.chartInteractionHint}
    >
      <ResponsiveContainer width="100%" height={430}>
        {chartMode === "line" ? (
          <LineChart data={visibleData} margin={chartMargin}>
            {chartGrid}
            {chartXAxis}
            {chartYAxis}
            {chartTooltip}
            {lineSeries}
          </LineChart>
        ) : chartMode === "bar" ? (
          <BarChart data={visibleData} margin={chartMargin}>
            {chartGrid}
            {chartXAxis}
            {chartYAxis}
            {chartTooltip}
            {barSeries}
          </BarChart>
        ) : (
          <AreaChart data={visibleData} margin={chartMargin}>
            {chartDefs}
            {chartGrid}
            {chartXAxis}
            {chartYAxis}
            {chartTooltip}
            {chartMode === "stacked" ? stackedSeries : areaSeries}
          </AreaChart>
        )}
      </ResponsiveContainer>
    </div>
  );
}
