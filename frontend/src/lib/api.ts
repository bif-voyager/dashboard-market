export type RangeValue = "7d" | "30d" | "90d" | "all";
export type SyncScope = "recent" | "all";
export type SyncPlatform = "polymarket" | "kalshi";
export type CategoryScope = "both" | "polymarket" | "kalshi";

export interface CategoryItem {
  slug: string;
  label: string;
  platforms: string[];
}

export interface VolumePoint {
  date: string;
  polymarket: number | null;
  kalshi: number | null;
  total: number;
}

export interface PlatformDataQuality {
  dailySeries: string;
  sourceType: "exact" | "derived" | "proxy" | "estimated";
  sourceLabel: string;
  categoryFilter: string;
  exact: boolean;
  isEstimated: boolean;
  partial: boolean;
  coverage: "full" | "partial" | "unknown";
  coverageReason?: string | null;
  rawTrades?: string | null;
}

export interface VolumeResponse {
  range: RangeValue;
  categories: string[];
  categoryScope: CategoryScope;
  timezone: string;
  asOf: string | null;
  partial: boolean;
  stale: boolean;
  warnings: string[];
  dataQuality?: {
    polymarket?: PlatformDataQuality;
    kalshi?: PlatformDataQuality;
  };
  totals: {
    polymarket: number;
    kalshi: number;
    difference: number;
    total: number;
  };
  points: VolumePoint[];
}

export interface SyncResponse {
  scope: SyncScope;
  platform?: SyncPlatform | null;
  status: string;
  partial: boolean;
  results: Record<string, Record<string, unknown>>;
}

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, init);
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const payload = await response.json();
      detail = payload.detail ?? detail;
    } catch {
      detail = response.statusText;
    }
    throw new ApiError(detail, response.status);
  }
  return response.json() as Promise<T>;
}

export async function fetchCategories(): Promise<CategoryItem[]> {
  return request<CategoryItem[]>("/api/categories");
}

export async function fetchVolume(
  range: RangeValue,
  categories: string[],
  categoryScope: CategoryScope,
): Promise<VolumeResponse> {
  const params = new URLSearchParams({ range });
  params.set("categories", categories.join(","));
  params.set("categoryScope", categoryScope);
  return request<VolumeResponse>(`/api/volume?${params.toString()}`);
}

export async function syncData(
  scope: SyncScope,
  platform?: SyncPlatform,
): Promise<SyncResponse> {
  const params = new URLSearchParams({ scope });
  if (platform) {
    params.set("platform", platform);
  }
  return request<SyncResponse>(`/api/admin/sync?${params.toString()}`, {
    method: "POST",
  });
}

export function buildCsvUrl(range: RangeValue, categories: string[], categoryScope: CategoryScope): string {
  const params = new URLSearchParams({
    range,
    categories: categories.join(","),
    categoryScope,
  });
  return `${API_BASE_URL}/api/export.csv?${params.toString()}`;
}
