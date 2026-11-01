import { api } from "@/services/api";
import type { MessageResponse, Page, PageParams } from "@/types/api";
import type {
  Permit,
  PermitStatus,
  PermitType,
  Visitor,
  VisitorStatus,
} from "@/types/models";

export interface VisitorPayload {
  compound_id: string;
  full_name: string;
  host_unit_id: string;
  national_id?: string | null;
  phone?: string | null;
  email?: string | null;
  company?: string | null;
  purpose?: string | null;
  expected_arrival?: string | null;
  notes?: string | null;
}

export interface PermitPayload {
  visitor_id: string;
  host_unit_id: string;
  start_at: string;
  end_at: string;
  permit_type?: PermitType;
  max_entries?: number;
  vehicle_plate?: string | null;
  notes?: string | null;
}

export async function listVisitors(params: PageParams): Promise<Page<Visitor>> {
  const { data } = await api.get<Page<Visitor>>("/visitors", { params });
  return data;
}

export async function createVisitor(payload: VisitorPayload): Promise<Visitor> {
  const { data } = await api.post<Visitor>("/visitors", payload);
  return data;
}

export async function updateVisitor(
  id: string,
  payload: Partial<VisitorPayload> & { status?: VisitorStatus },
): Promise<Visitor> {
  const { data } = await api.patch<Visitor>(`/visitors/${id}`, payload);
  return data;
}

export async function visitorAction(
  id: string,
  action: "approve" | "reject" | "check-in" | "check-out",
): Promise<Visitor> {
  const { data } = await api.post<Visitor>(`/visitors/${id}/${action}`);
  return data;
}

export async function deleteVisitor(id: string): Promise<MessageResponse> {
  const { data } = await api.delete<MessageResponse>(`/visitors/${id}`);
  return data;
}

export async function uploadVisitorPhoto(id: string, file: File): Promise<Visitor> {
  const form = new FormData();
  form.append("file", file);
  const { data } = await api.post<Visitor>(`/visitors/${id}/photo`, form);
  return data;
}

export async function listPermits(params: PageParams): Promise<Page<Permit>> {
  const { data } = await api.get<Page<Permit>>("/permits", { params });
  return data;
}

export async function createPermit(payload: PermitPayload): Promise<Permit> {
  const { data } = await api.post<Permit>("/permits", payload);
  return data;
}

export async function revokePermit(id: string, reason: string): Promise<Permit> {
  const { data } = await api.post<Permit>(`/permits/${id}/revoke`, { reason });
  return data;
}

export interface PermitUpdatePayload {
  status?: PermitStatus;
  notes?: string | null;
  max_entries?: number;
  permit_type?: PermitType;
  start_at?: string;
  end_at?: string;
  vehicle_id?: string | null;
}

export async function updatePermit(
  id: string,
  payload: PermitUpdatePayload,
): Promise<Permit> {
  const { data } = await api.patch<Permit>(`/permits/${id}`, payload);
  return data;
}
