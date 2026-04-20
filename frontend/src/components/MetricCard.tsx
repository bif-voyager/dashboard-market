interface MetricCardProps {
  title: string;
  value: string;
  tone: "sea" | "ember" | "ink";
  badge?: string;
  detail?: string;
}

export function MetricCard({ title, value, tone, badge, detail }: MetricCardProps) {
  return (
    <article className={`metric-card metric-card--${tone}`}>
      <div className="metric-card__header">
        <span className="metric-card__title">{title}</span>
        {badge ? <span className="metric-card__badge">{badge}</span> : null}
      </div>
      <strong className="metric-card__value">{value}</strong>
      {detail ? <p className="metric-card__detail">{detail}</p> : null}
    </article>
  );
}
