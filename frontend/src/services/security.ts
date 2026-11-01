import { api } from "@/services/api";
import type { MessageResponse, Page, PageParams } from "@/types/api";
import type {
  BlacklistEntry,
  BlacklistEntryType,
  BlacklistReason,
  FaceEmbedding,
  FaceGalleryInfo,
  FaceQualityReport,
} from "@/types/models";

export interface BlacklistPayload {
  compound_id: string;
  entry_type: BlacklistEntryType;
  plate_number?: string | null;
  person_name?: string | null;
  national_id?: string | null;
  resident_id?: string | null;
  reason?: BlacklistReason;
  description?: string | null;
  expires_at?: string | null;
  is_active?: boolean;
}

export async function listBlacklist(params: PageParams): Promise<Page<BlacklistEntry>> {
  const { data } = await api.get<Page<BlacklistEntry>>("/blacklist", { params });
  return data;
}

export async function createBlacklistEntry(
  payload: BlacklistPayload,
): Promise<BlacklistEntry> {
  const { data } = await api.post<BlacklistEntry>("/blacklist", payload);
  return data;
}

export async function updateBlacklistEntry(
  id: string,
  payload: Partial<BlacklistPayload>,
): Promise<BlacklistEntry> {
  const { data } = await api.patch<BlacklistEntry>(`/blacklist/${id}`, payload);
  return data;
}

export async function deleteBlacklistEntry(id: string): Promise<MessageResponse> {
  const { data } = await api.delete<MessageResponse>(`/blacklist/${id}`);
  return data;
}

export async function listFaces(params: PageParams): Promise<Page<FaceEmbedding>> {
  const { data } = await api.get<Page<FaceEmbedding>>("/faces", { params });
  return data;
}

export async function enrollFace(
  residentId: string,
  file: File,
  overwrite = false,
): Promise<FaceEmbedding> {
  const form = new FormData();
  form.append("resident_id", residentId);
  form.append("overwrite", String(overwrite));
  form.append("file", file);
  const { data } = await api.post<FaceEmbedding>("/faces/enroll", form);
  return data;
}

/**
 * Pre-flight a photo before enrollment. Nothing is persisted; the API returns
 * the score, every failed check and the compound thresholds so the modal can
 * explain exactly what to fix.
 */
export async function checkFaceQuality(
  residentId: string,
  file: File,
): Promise<FaceQualityReport> {
  const form = new FormData();
  form.append("resident_id", residentId);
  form.append("file", file);
  const { data } = await api.post<FaceQualityReport>("/faces/quality-check", form);
  return data;
}

export async function deactivateFace(id: string): Promise<FaceEmbedding> {
  const { data } = await api.post<FaceEmbedding>(`/faces/${id}/deactivate`);
  return data;
}

export async function deleteFace(id: string): Promise<MessageResponse> {
  const { data } = await api.delete<MessageResponse>(`/faces/${id}`);
  return data;
}

export async function fetchFaceGallery(): Promise<FaceGalleryInfo> {
  const { data } = await api.get<FaceGalleryInfo>("/cv/gallery");
  return data;
}

export async function refreshFaceGallery(): Promise<MessageResponse> {
  const { data } = await api.post<MessageResponse>("/cv/refresh-gallery");
  return data;
}

export async function fetchBlacklistBreakdown(): Promise<Record<string, number>> {
  const { data } = await api.get<Record<string, number>>("/analytics/blacklist-breakdown");
  return data;
}
