import { api } from "@/services/api";
import type { MessageResponse, Page, PageParams } from "@/types/api";
import type {
  Camera,
  CameraSourceType,
  Compound,
  Gate,
  GateDirection,
  GateStatus,
  User,
  UserRole,
} from "@/types/models";

export interface GatePayload {
  compound_id: string;
  name: string;
  code: string;
  direction?: GateDirection;
  status?: GateStatus;
  location?: string | null;
  notes?: string | null;
}

export interface CameraPayload {
  gate_id: string;
  name: string;
  source_type: CameraSourceType;
  source_url: string;
  fps_limit?: number;
  position?: string;
  notes?: string | null;
}

export interface UserPayload {
  email: string;
  full_name: string;
  password?: string;
  role: UserRole;
  compound_id?: string | null;
  phone?: string | null;
  is_active?: boolean;
}

export async function listCompounds(): Promise<Page<Compound>> {
  const { data } = await api.get<Page<Compound>>("/compounds", {
    params: { page_size: 100 },
  });
  return data;
}

export async function updateCompound(
  id: string,
  payload: Partial<Compound>,
): Promise<Compound> {
  const { data } = await api.patch<Compound>(`/compounds/${id}`, payload);
  return data;
}

export async function listGates(compoundId?: string): Promise<Page<Gate>> {
  const { data } = await api.get<Page<Gate>>("/gates", {
    params: { page_size: 100, compound_id: compoundId },
  });
  return data;
}

export async function createGate(payload: GatePayload): Promise<Gate> {
  const { data } = await api.post<Gate>("/gates", payload);
  return data;
}

export async function updateGate(id: string, payload: Partial<GatePayload>): Promise<Gate> {
  const { data } = await api.patch<Gate>(`/gates/${id}`, payload);
  return data;
}

export async function deleteGate(id: string): Promise<MessageResponse> {
  const { data } = await api.delete<MessageResponse>(`/gates/${id}`);
  return data;
}

export async function gateCommand(
  id: string,
  action: "open" | "close" | "hold",
  reason = "Dashboard command",
): Promise<{ accepted: boolean; detail: string }> {
  const { data } = await api.post<{ accepted: boolean; detail: string }>(
    `/gates/${id}/command`,
    { action, reason },
  );
  return data;
}

export async function listCameras(): Promise<Page<Camera>> {
  const { data } = await api.get<Page<Camera>>("/cameras", { params: { page_size: 100 } });
  return data;
}

export async function createCamera(payload: CameraPayload): Promise<Camera> {
  const { data } = await api.post<Camera>("/cameras", payload);
  return data;
}

export async function updateCamera(
  id: string,
  payload: Partial<CameraPayload & { is_active: boolean }>,
): Promise<Camera> {
  const { data } = await api.patch<Camera>(`/cameras/${id}`, payload);
  return data;
}

export async function toggleCamera(id: string, active: boolean): Promise<Camera> {
  const { data } = await api.post<Camera>(`/cameras/${id}/toggle`, null, {
    params: { active },
  });
  return data;
}

export async function deleteCamera(id: string): Promise<MessageResponse> {
  const { data } = await api.delete<MessageResponse>(`/cameras/${id}`);
  return data;
}

export async function listUsers(params: PageParams = {}): Promise<Page<User>> {
  const { data } = await api.get<Page<User>>("/users", {
    params: { page_size: 100, ...params },
  });
  return data;
}

export async function createUser(payload: UserPayload): Promise<User> {
  const { data } = await api.post<User>("/users", payload);
  return data;
}

export async function updateUser(id: string, payload: Partial<UserPayload>): Promise<User> {
  const { data } = await api.patch<User>(`/users/${id}`, payload);
  return data;
}

export async function resetUserPassword(
  id: string,
  newPassword: string,
): Promise<MessageResponse> {
  const { data } = await api.post<MessageResponse>(`/users/${id}/reset-password`, {
    new_password: newPassword,
  });
  return data;
}

export async function deactivateUser(id: string): Promise<MessageResponse> {
  const { data } = await api.delete<MessageResponse>(`/users/${id}`);
  return data;
}
