export type RangeValue = "7d" | "30d" | "90d" | "all";
export type SyncScope = "recent" | "all";

export interface CategoryItem {
  slug: string;
  label: string;
  platforms: string[];
}

export interface VolumePoint {
  date: string;
  polymarket: number;
  kalshi: number;
  total: number;
}

export interface VolumeResponse {
  range: RangeValue;
  categories: string[];
  timezone: string;
  asOf: string | null;
  partial: boolean;
  stale: boolean;
  warnings: string[];
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

export async function fetchVolume(range: RangeValue, categories: string[]): Promise<VolumeResponse> {
  const params = new URLSearchParams({ range });
  params.set("categories", categories.join(","));
  return request<VolumeResponse>(`/api/volume?${params.toString()}`);
}

export async function syncData(scope: SyncScope): Promise<SyncResponse> {
  return request<SyncResponse>(`/api/admin/sync?scope=${scope}`, {
    method: "POST",
  });
}

export function buildCsvUrl(range: RangeValue, categories: string[]): string {
  const params = new URLSearchParams({ range, categories: categories.join(",") });
  return `${API_BASE_URL}/api/export.csv?${params.toString()}`;
}
