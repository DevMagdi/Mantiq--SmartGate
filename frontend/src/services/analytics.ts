import { api } from "@/services/api";
import type {
  DashboardData,
  OccupancySnapshot,
  OverviewStats,
  TrendPoint,
} from "@/types/models";

export async function fetchDashboard(days = 7): Promise<DashboardData> {
  const { data } = await api.get<DashboardData>("/analytics/dashboard", {
    params: { days },
  });
  return data;
}

export async function fetchOverview(): Promise<OverviewStats> {
  const { data } = await api.get<OverviewStats>("/analytics/overview");
  return data;
}

export async function fetchTrend(days = 7): Promise<TrendPoint[]> {
  const { data } = await api.get<TrendPoint[]>("/analytics/trend", { params: { days } });
  return data;
}

export async function fetchOccupancy(): Promise<OccupancySnapshot> {
  const { data } = await api.get<OccupancySnapshot>("/analytics/occupancy");
  return data;
}

export async function fetchBlacklistBreakdown(): Promise<Record<string, number>> {
  const { data } = await api.get<Record<string, number>>("/analytics/blacklist-breakdown");
  return data;
}
