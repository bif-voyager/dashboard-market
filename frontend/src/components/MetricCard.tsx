interface MetricCardProps {
  title: string;
  value: string;
  tone: "sea" | "ember" | "ink";
}

export function MetricCard({ title, value, tone }: MetricCardProps) {
  return (
    <article className={`metric-card metric-card--${tone}`}>
      <span className="metric-card__title">{title}</span>
      <strong className="metric-card__value">{value}</strong>
    </article>
  );
}
