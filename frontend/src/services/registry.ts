import { api } from "@/services/api";
import type { MessageResponse, Page, PageParams } from "@/types/api";
import type {
  Resident,
  ResidentStatus,
  Unit,
  UnitStatus,
  UnitType,
  Vehicle,
  VehicleStatus,
  VehicleType,
} from "@/types/models";

export interface ResidentPayload {
  compound_id: string;
  unit_id: string;
  full_name: string;
  national_id?: string | null;
  phone?: string | null;
  email?: string | null;
  role_in_unit?: string;
  status?: ResidentStatus;
  is_primary?: boolean;
  notes?: string | null;
  create_account?: boolean;
  account_password?: string | null;
}

export async function listResidents(params: PageParams): Promise<Page<Resident>> {
  const { data } = await api.get<Page<Resident>>("/residents", { params });
  return data;
}

export async function getMyResidentProfile(): Promise<Resident> {
  const { data } = await api.get<Resident>("/residents/me");
  return data;
}

export async function createResident(payload: ResidentPayload): Promise<Resident> {
  const { data } = await api.post<Resident>("/residents", payload);
  return data;
}

export async function updateResident(
  id: string,
  payload: Partial<ResidentPayload>,
): Promise<Resident> {
  const { data } = await api.patch<Resident>(`/residents/${id}`, payload);
  return data;
}

export async function deleteResident(id: string): Promise<MessageResponse> {
  const { data } = await api.delete<MessageResponse>(`/residents/${id}`);
  return data;
}

export interface UnitListParams extends PageParams {
  status?: UnitStatus;
  unit_type?: UnitType;
  building?: string;
  search?: string;
}

/** Every field the API accepts on ``POST/PATCH /compounds/{id}/units``. */
export interface UnitPayload {
  building: string;
  unit_number: string;
  floor?: number;
  unit_type?: UnitType;
  status?: UnitStatus;
  bedrooms?: number | null;
  area_sqm?: number | null;
  notes?: string | null;
}

export async function listUnits(
  compoundId: string,
  params: UnitListParams = {},
): Promise<Page<Unit>> {
  const { data } = await api.get<Page<Unit>>(`/compounds/${compoundId}/units`, {
    params: { page_size: 200, ...params },
  });
  return data;
}

export async function createUnit(
  compoundId: string,
  payload: UnitPayload,
): Promise<Unit> {
  const { data } = await api.post<Unit>(`/compounds/${compoundId}/units`, payload);
  return data;
}

export async function updateUnit(
  compoundId: string,
  unitId: string,
  payload: Partial<UnitPayload>,
): Promise<Unit> {
  const { data } = await api.patch<Unit>(
    `/compounds/${compoundId}/units/${unitId}`,
    payload,
  );
  return data;
}

export async function deleteUnit(
  compoundId: string,
  unitId: string,
): Promise<MessageResponse> {
  const { data } = await api.delete<MessageResponse>(
    `/compounds/${compoundId}/units/${unitId}`,
  );
  return data;
}

export interface VehiclePayload {
  compound_id: string;
  resident_id?: string | null;
  plate_number: string;
  make?: string | null;
  model?: string | null;
  color?: string | null;
  year?: number | null;
  vehicle_type?: VehicleType;
  status?: VehicleStatus;
  sticker_number?: string | null;
  notes?: string | null;
}

export async function listVehicles(params: PageParams): Promise<Page<Vehicle>> {
  const { data } = await api.get<Page<Vehicle>>("/vehicles", { params });
  return data;
}

export async function createVehicle(payload: VehiclePayload): Promise<Vehicle> {
  const { data } = await api.post<Vehicle>("/vehicles", payload);
  return data;
}

export async function updateVehicle(
  id: string,
  payload: Partial<VehiclePayload>,
): Promise<Vehicle> {
  const { data } = await api.patch<Vehicle>(`/vehicles/${id}`, payload);
  return data;
}

export async function deleteVehicle(id: string): Promise<MessageResponse> {
  const { data } = await api.delete<MessageResponse>(`/vehicles/${id}`);
  return data;
}
