/** Generic API envelopes and realtime event payloads. */

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

export interface MessageResponse {
  message: string;
  detail?: string | null;
}

export interface ApiErrorBody {
  code: string;
  message: string;
  details?: unknown;
  request_id?: string | null;
}

export interface ApiErrorResponse {
  error: ApiErrorBody;
}

export interface PageParams {
  page?: number;
  page_size?: number;
  search?: string;
  sort_by?: string;
  sort_dir?: "asc" | "desc";
  [key: string]: string | number | boolean | undefined;
}

export interface HealthResponse {
  status: string;
  version: string;
  environment: string;
  database: boolean;
  redis: boolean;
  cv_mode: string;
  timestamp: string;
}

export interface StreamEvent {
  id: string;
  type: string;
  occurred_at: string;
  payload: Record<string, unknown>;
}

export interface DetectionStreamPayload {
  access_log_id?: string;
  detection_event_id?: string;
  gate_id?: string;
  gate_name?: string;
  direction?: string;
  decision?: string;
  reason?: string;
  reason_code?: string;
  plate_text?: string | null;
  plate_confidence?: number | null;
  face_similarity?: number | null;
  face_matched?: boolean;
  snapshot_url?: string | null;
  face_snapshot_url?: string | null;
  method?: string;
  gate_opened?: boolean;
  occurred_at?: string;
  processing_ms?: number | null;
  requires_review?: boolean;
}
