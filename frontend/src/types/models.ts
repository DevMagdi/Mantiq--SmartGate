/**
 * Domain types mirroring the FastAPI response schemas.
 * Keeping them in one place makes it obvious when the API contract changes.
 */

export type UserRole = "admin" | "security_officer" | "resident";
export type GateDirection = "entry" | "exit" | "bidirectional";
export type GateStatus = "online" | "offline" | "maintenance";
export type CameraSourceType = "rtsp" | "usb" | "file" | "demo";
export type CameraStatus = "online" | "offline" | "error" | "disabled";
export type UnitType = "apartment" | "villa" | "townhouse" | "office" | "other";
export type UnitStatus = "occupied" | "vacant";
export type ResidentRelationship = "owner" | "tenant" | "family";
export type ResidentStatus = "active" | "inactive" | "moved_out";
export type VehicleType = "car" | "motorcycle" | "van" | "truck" | "other";
export type VehicleStatus = "active" | "suspended" | "inactive";
export type VisitorStatus =
  | "pending"
  | "approved"
  | "rejected"
  | "checked_in"
  | "checked_out"
  | "expired"
  | "cancelled";
export type PermitType =
  | "visitor"
  | "contractor"
  | "delivery"
  | "temporary_resident"
  | "event";
export type PermitStatus = "pending" | "active" | "expired" | "revoked";
export type AccessDecision = "allow" | "deny" | "unknown" | "review";
export type AccessMethod = "plate" | "face" | "combined" | "permit" | "manual";
export type AccessDirection = "entry" | "exit";
export type DetectionType = "plate" | "face" | "combined" | "manual";
export type BlacklistEntryType = "plate" | "face" | "person";
export type BlacklistReason =
  | "theft"
  | "security"
  | "unpaid_dues"
  | "trespassing"
  | "court_order"
  | "other";
export type EmbeddingSource = "enrollment" | "detection";

export interface User {
  id: string;
  email: string;
  full_name: string;
  phone: string | null;
  role: UserRole;
  is_active: boolean;
  compound_id: string | null;
  last_login_at: string | null;
  created_at: string;
  updated_at: string;
  resident_id: string | null;
}

export interface TokenPair {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
  user: User;
}

export interface Compound {
  id: string;
  name: string;
  code: string;
  address: string | null;
  city: string | null;
  country: string;
  timezone: string;
  contact_email: string | null;
  contact_phone: string | null;
  logo_url: string | null;
  is_active: boolean;
  settings: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface CompoundBrief {
  id: string;
  name: string;
  code: string;
}

export interface Camera {
  id: string;
  gate_id: string;
  name: string;
  source_type: CameraSourceType;
  source_url: string;
  is_active: boolean;
  status: CameraStatus;
  fps_limit: number;
  position: string;
  resolution: string | null;
  last_frame_at: string | null;
  last_error: string | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

export interface CameraBrief {
  id: string;
  name: string;
  status: CameraStatus;
  position: string;
}

export interface Gate {
  id: string;
  compound_id: string;
  name: string;
  code: string;
  direction: GateDirection;
  status: GateStatus;
  location: string | null;
  notes: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
  cameras: CameraBrief[];
}

export interface GateBrief {
  id: string;
  name: string;
  code: string;
  direction: GateDirection;
  status: GateStatus;
}

export interface Unit {
  id: string;
  compound_id: string;
  building: string;
  unit_number: string;
  floor: number;
  unit_type: UnitType;
  status: UnitStatus;
  bedrooms: number | null;
  area_sqm: number | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
  label: string;
}

export interface UnitBrief {
  id: string;
  building: string;
  unit_number: string;
  label: string;
}

export interface ResidentBrief {
  id: string;
  full_name: string;
  phone: string | null;
  status: ResidentStatus;
}

export interface Resident {
  id: string;
  compound_id: string;
  unit_id: string;
  user_id: string | null;
  full_name: string;
  national_id: string | null;
  phone: string | null;
  email: string | null;
  role_in_unit: ResidentRelationship;
  status: ResidentStatus;
  is_primary: boolean;
  move_in_date: string | null;
  move_out_date: string | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
  unit: UnitBrief | null;
  vehicle_count: number;
  face_count: number;
}

export interface VehicleBrief {
  id: string;
  plate_number: string;
  make: string | null;
  model: string | null;
  color: string | null;
  status: VehicleStatus;
}

export interface Vehicle {
  id: string;
  compound_id: string;
  resident_id: string | null;
  plate_number: string;
  plate_normalized: string;
  make: string | null;
  model: string | null;
  color: string | null;
  year: number | null;
  vehicle_type: VehicleType;
  status: VehicleStatus;
  sticker_number: string | null;
  is_inside: boolean;
  last_seen_at: string | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
  resident: ResidentBrief | null;
}

export interface VisitorBrief {
  id: string;
  full_name: string;
  phone: string | null;
  status: VisitorStatus;
}

export interface Visitor {
  id: string;
  compound_id: string;
  host_unit_id: string;
  host_resident_id: string | null;
  full_name: string;
  national_id: string | null;
  phone: string | null;
  email: string | null;
  company: string | null;
  purpose: string | null;
  photo_url: string | null;
  status: VisitorStatus;
  expected_arrival: string | null;
  actual_arrival: string | null;
  actual_departure: string | null;
  notes: string | null;
  created_by_id: string | null;
  created_at: string;
  updated_at: string;
  host_unit: UnitBrief | null;
  active_permit_count: number;
}

export interface PermitBrief {
  id: string;
  permit_code: string;
  permit_type: PermitType;
  status: PermitStatus;
  start_at: string;
  end_at: string;
  entries_used: number;
  max_entries: number;
}

export interface Permit {
  id: string;
  compound_id: string;
  visitor_id: string;
  vehicle_id: string | null;
  host_unit_id: string;
  host_resident_id: string | null;
  permit_code: string;
  permit_type: PermitType;
  status: PermitStatus;
  start_at: string;
  end_at: string;
  max_entries: number;
  entries_used: number;
  notes: string | null;
  revoked_at: string | null;
  revoked_reason: string | null;
  created_at: string;
  updated_at: string;
  visitor: VisitorBrief | null;
  host_unit: UnitBrief | null;
  vehicle_plate: string | null;
}

export interface AccessLog {
  id: string;
  compound_id: string;
  gate_id: string;
  camera_id: string | null;
  direction: AccessDirection;
  occurred_at: string;
  decision: AccessDecision;
  reason_code: string;
  reason: string;
  access_method: AccessMethod;
  plate_number: string | null;
  plate_confidence: number | null;
  face_similarity: number | null;
  vehicle_id: string | null;
  resident_id: string | null;
  visitor_id: string | null;
  permit_id: string | null;
  snapshot_url: string | null;
  face_snapshot_url: string | null;
  gate_opened: boolean;
  is_overridden: boolean;
  override_by_id: string | null;
  override_reason: string | null;
  overridden_at: string | null;
  notes: string | null;
  created_at: string;
  gate: GateBrief | null;
  camera: CameraBrief | null;
  vehicle: VehicleBrief | null;
  resident: ResidentBrief | null;
  visitor: VisitorBrief | null;
  permit: PermitBrief | null;
}

export interface DetectionEvent {
  id: string;
  compound_id: string;
  gate_id: string;
  camera_id: string | null;
  occurred_at: string;
  event_type: DetectionType;
  plate_text: string | null;
  plate_confidence: number | null;
  plate_bbox: Record<string, number> | null;
  plate_snapshot_url: string | null;
  face_snapshot_url: string | null;
  face_detected: boolean;
  face_matched: boolean;
  face_similarity: number | null;
  matched_resident_id: string | null;
  matched_vehicle_id: string | null;
  decision: AccessDecision;
  decision_reason: string | null;
  access_log_id: string | null;
  vision_engine: string;
  processing_ms: number | null;
  raw_payload: Record<string, unknown>;
  created_at: string;
  gate: GateBrief | null;
  camera: CameraBrief | null;
  matched_resident: ResidentBrief | null;
  matched_vehicle: VehicleBrief | null;
}

export interface BlacklistEntry {
  id: string;
  compound_id: string;
  entry_type: BlacklistEntryType;
  plate_number: string | null;
  plate_normalized: string | null;
  resident_id: string | null;
  visitor_id: string | null;
  face_embedding_id: string | null;
  person_name: string | null;
  national_id: string | null;
  reason: BlacklistReason;
  description: string | null;
  is_active: boolean;
  expires_at: string | null;
  created_by_id: string | null;
  created_at: string;
  updated_at: string;
  resident: ResidentBrief | null;
}

export interface FaceEmbedding {
  id: string;
  compound_id: string;
  resident_id: string | null;
  visitor_id: string | null;
  dimension: number;
  model_name: string;
  quality: number | null;
  image_url: string | null;
  source: EmbeddingSource;
  is_active: boolean;
  created_at: string;
  updated_at: string;
  resident: ResidentBrief | null;
  similarity_to_existing: number | null;
}

export interface FaceGalleryInfo {
  total_embeddings: number;
  active_embeddings: number;
  enrolled_residents: number;
  model_name: string;
  threshold: number;
}

export interface OverviewStats {
  entries_today: number;
  exits_today: number;
  allowed_today: number;
  denied_today: number;
  unknown_today: number;
  review_today: number;
  face_match_rate: number;
  plate_read_rate: number;
  unique_vehicles_today: number;
  vehicles_inside: number;
  active_visitors: number;
  active_permits: number;
  residents_total: number;
  vehicles_total: number;
  blacklist_active: number;
  cameras_online: number;
  cameras_total: number;
  avg_processing_ms: number | null;
  entries_change_pct: number | null;
}

export interface PeakHourPoint {
  hour: number;
  label: string;
  entries: number;
  exits: number;
  total: number;
}

export interface TrendPoint {
  day: string;
  allowed: number;
  denied: number;
  unknown: number;
  review: number;
  total: number;
}

export interface DecisionBreakdown {
  decision: AccessDecision;
  count: number;
  percentage: number;
}

export interface MethodBreakdown {
  method: string;
  count: number;
}

export interface ReasonBreakdown {
  reason_code: string;
  decision: AccessDecision;
  count: number;
  percentage: number;
}

export interface GatePerformance {
  gate_id: string;
  gate_name: string;
  gate_code: string;
  direction: GateDirection;
  total: number;
  allowed: number;
  denied: number;
  unknown: number;
  review: number;
  last_activity_at: string | null;
}

export interface HeatmapCell {
  day_of_week: number;
  hour: number;
  count: number;
}

export interface DashboardData {
  generated_at: string;
  range_start: string;
  range_end: string;
  overview: OverviewStats;
  peak_hours: PeakHourPoint[];
  trend: TrendPoint[];
  decision_breakdown: DecisionBreakdown[];
  method_breakdown: MethodBreakdown[];
  gate_performance: GatePerformance[];
  reason_breakdown: ReasonBreakdown[];
  barrier_failures: number;
  heatmap: HeatmapCell[];
  recent_access: AccessLog[];
  recent_detections: DetectionEvent[];
}

export interface OccupancySnapshot {
  inside_now: number;
  entries_today: number;
  exits_today: number;
  net_change: number;
  by_gate: GatePerformance[];
}

export interface VisionPipelineStatus {
  mode: string;
  plate_detector: string;
  ocr_engine: string;
  face_engine: string;
  engine_ready: boolean;
  models_loaded: string[];
  warnings: string[];
  face_gallery_size: number;
  similarity_threshold: number;
}

export interface CameraHealthItem {
  camera_id: string;
  name: string;
  gate_id: string;
  gate_name: string;
  gate_code: string;
  source_type: string;
  source: string;
  is_active: boolean;
  status: string;
  stale: boolean;
  resolution: string | null;
  fps_limit: number;
  last_frame_at: string | null;
  frame_age_seconds: number | null;
  last_error: string | null;
  worker_alive: boolean | null;
  observed_fps: number | null;
}

export interface CameraHealthResponse {
  compound_id: string;
  generated_at: string;
  stale_after_seconds: number;
  counts: {
    total: number;
    online: number;
    offline: number;
    error: number;
    disabled: number;
    stale: number;
    demo: number;
  };
  total: number;
  online: number;
  offline: number;
  error: number;
  disabled: number;
  stale: number;
  demo: number;
  cameras: CameraHealthItem[];
}

export interface CameraProbeResult {
  ok: boolean;
  camera_id: string;
  camera_name: string;
  source: string;
  source_type: string;
  frames: number;
  latency_ms: number;
  open_ms: number;
  width: number | null;
  height: number | null;
  brightness: number | null;
  preview_url: string | null;
  error: string | null;
  hint: string | null;
}

export interface RealModeStatus {
  mode: string;
  real_detections_only: boolean;
  engine_ready: boolean;
  warnings: string[];
  cameras_total: number;
  cameras_online: number;
  demo_cameras: number;
  barrier_driver: string;
  models: Record<string, string>;
}

export type BarrierDriver = "simulator" | "webhook" | "mqtt" | "gpio";

export interface ActuatorCommand {
  id: string;
  occurred_at: string;
  gate_code: string;
  gate_id: string | null;
  compound_id: string | null;
  action: string;
  driver: string;
  accepted: boolean;
  latency_ms: number;
  attempts: number;
  detail: string;
  actor: string;
  reason: string;
  error: string | null;
  external_status: number | null;
  extra: Record<string, unknown>;
}

export interface ActuatorStatusEntry {
  compound_id: string | null;
  compound_name: string | null;
  configured: boolean;
  driver: BarrierDriver | string;
  name: string | null;
  config: {
    driver?: string;
    webhook?: { url?: string | null; signed?: boolean } | null;
    mqtt?: { host?: string; port?: number; topic?: string; simulated?: boolean } | null;
    gpio?: { open_pin?: number; close_pin?: number; simulated?: boolean } | null;
    [key: string]: unknown;
  };
  health: Record<string, unknown>;
  warnings: string[];
  journal: Record<string, unknown>;
  recent_commands: ActuatorCommand[];
}

export interface ActuatorStatusResponse {
  compounds: ActuatorStatusEntry[];
  journal: Record<string, unknown>;
}

export interface ActuatorTestResult {
  gate_id: string;
  action: string;
  accepted: boolean;
  detail: string;
  driver: string;
  latency_ms: number;
  command_id: string | null;
}

export interface VisionAnalyzeResult {
  plate_text: string | null;
  plate_confidence: number | null;
  plate_snapshot_url: string | null;
  face_detected: boolean;
  face_matched: boolean;
  face_similarity: number | null;
  matched_resident_id: string | null;
  decision: AccessDecision;
  reason_code: string;
  reason: string;
  access_method: AccessMethod;
  detection_event_id: string | null;
  access_log_id: string | null;
  processing_ms: number | null;
}

export interface DemoScenario {
  key: string;
  label: string;
  description: string;
}
