import { api } from "@/services/api";
import type { Page, PageParams } from "@/types/api";
import type {
  AccessDecision,
  AccessDirection,
  AccessLog,
  DetectionEvent,
} from "@/types/models";

export interface AccessLogFilters extends PageParams {
  decision?: AccessDecision;
  direction?: AccessDirection;
  gate_id?: string;
  plate?: string;
  start?: string;
  end?: string;
  overridden?: boolean;
  requires_review?: boolean;
  resident_id?: string;
}

export async function listAccessLogs(
  params: AccessLogFilters,
): Promise<Page<AccessLog>> {
  const { data } = await api.get<Page<AccessLog>>("/access-logs", { params });
  return data;
}

export async function getAccessLog(id: string): Promise<AccessLog> {
  const { data } = await api.get<AccessLog>(`/access-logs/${id}`);
  return data;
}

export async function overrideAccessLog(
  id: string,
  payload: {
    decision: AccessDecision;
    reason: string;
    open_gate?: boolean;
    notes?: string;
  },
): Promise<AccessLog> {
  const { data } = await api.post<AccessLog>(`/access-logs/${id}/override`, payload);
  return data;
}

export async function createManualEntry(payload: {
  gate_id: string;
  decision?: AccessDecision;
  direction?: AccessDirection;
  plate_number?: string | null;
  reason: string;
  notes?: string | null;
  open_gate?: boolean;
}): Promise<AccessLog> {
  const { data } = await api.post<AccessLog>("/access-logs/manual", payload);
  return data;
}

export async function listDetections(
  params: AccessLogFilters & { event_type?: string },
): Promise<Page<DetectionEvent>> {
  const { data } = await api.get<Page<DetectionEvent>>("/detections", { params });
  return data;
}

export async function downloadAccessLogs(
  format: "csv" | "xlsx",
  filters: AccessLogFilters,
): Promise<void> {
  const { data, headers } = await api.get<Blob>("/access-logs/export", {
    params: { ...filters, format },
    responseType: "blob",
  });
  const disposition = String(headers["content-disposition"] ?? "");
  const match = disposition.match(/filename="?([^";]+)"?/);
  const filename = match?.[1] ?? `gatevision-access-logs.${format}`;
  const url = URL.createObjectURL(data);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}
