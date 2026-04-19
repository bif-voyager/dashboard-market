import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { VolumePoint } from "../lib/api";
import { formatCompactCurrency, formatCurrency, formatDateLabel } from "../lib/format";

interface VolumeChartProps {
  data: VolumePoint[];
}

export function VolumeChart({ data }: VolumeChartProps) {
  return (
    <div className="chart-shell">
      <ResponsiveContainer width="100%" height={380}>
        <LineChart data={data} margin={{ top: 20, right: 12, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 6" stroke="rgba(32, 42, 53, 0.15)" vertical={false} />
          <XAxis
            dataKey="date"
            tickFormatter={formatDateLabel}
            tick={{ fill: "rgba(32, 42, 53, 0.72)", fontSize: 12 }}
            axisLine={false}
            tickLine={false}
            minTickGap={28}
          />
          <YAxis
            tickFormatter={formatCompactCurrency}
            tick={{ fill: "rgba(32, 42, 53, 0.72)", fontSize: 12 }}
            axisLine={false}
            tickLine={false}
            width={86}
          />
          <Tooltip
            contentStyle={{
              borderRadius: 18,
              border: "1px solid rgba(32, 42, 53, 0.12)",
              boxShadow: "0 20px 50px rgba(32, 42, 53, 0.12)",
              background: "rgba(255,255,255,0.95)",
            }}
            formatter={(value: number, name: string) => [formatCurrency(value), name === "polymarket" ? "Polymarket" : "Kalshi"]}
            labelFormatter={(label: string) =>
              new Date(`${label}T00:00:00Z`).toLocaleDateString("en-US", {
                weekday: "short",
                month: "short",
                day: "numeric",
                year: "numeric",
              })
            }
          />
          <Line
            type="monotone"
            dataKey="polymarket"
            stroke="#0d9488"
            strokeWidth={3}
            dot={false}
            activeDot={{ r: 5, fill: "#0d9488" }}
          />
          <Line
            type="monotone"
            dataKey="kalshi"
            stroke="#c2410c"
            strokeWidth={3}
            dot={false}
            activeDot={{ r: 5, fill: "#c2410c" }}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
