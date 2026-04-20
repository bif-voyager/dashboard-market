export function formatCurrency(value: number, locale = "en-US"): string {
  return new Intl.NumberFormat(locale, {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(value);
}

export function formatCompactCurrency(value: number, locale = "en-US"): string {
  return new Intl.NumberFormat(locale, {
    style: "currency",
    currency: "USD",
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(value);
}

export function formatDateLabel(value: string, locale = "en-US"): string {
  return new Date(`${value}T00:00:00Z`).toLocaleDateString(locale, {
    month: "short",
    day: "numeric",
  });
}

export function formatAsOf(value: string | null, locale = "en-US", emptyLabel = "No synced data yet"): string {
  if (!value) {
    return emptyLabel;
  }
  if (value.includes("T")) {
    return new Date(value).toLocaleString(locale);
  }
  return new Date(`${value}T00:00:00Z`).toLocaleDateString(locale, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}
