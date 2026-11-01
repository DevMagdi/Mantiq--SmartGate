import type {
  AccessDecision,
  BlacklistEntryType,
  GateStatus,
  PermitStatus,
  ResidentStatus,
  UserRole,
  VehicleStatus,
  VisitorStatus,
} from "@/types/models";

export type Tone = "success" | "danger" | "warning" | "info" | "neutral" | "brand";

export const ROLE_LABELS: Record<UserRole, string> = {
  admin: "Administrator",
  security_officer: "Security Officer",
  resident: "Resident",
};

export const DECISION_META: Record<
  AccessDecision,
  { label: string; tone: Tone; description: string }
> = {
  allow: { label: "Allowed", tone: "success", description: "Barrier released automatically" },
  deny: { label: "Denied", tone: "danger", description: "Access refused by policy" },
  unknown: { label: "Unknown", tone: "warning", description: "No matching plate or face" },
  review: { label: "Manual review", tone: "info", description: "Waiting for an officer decision" },
};

export const GATE_STATUS_META: Record<GateStatus, { label: string; tone: Tone }> = {
  online: { label: "Online", tone: "success" },
  offline: { label: "Offline", tone: "neutral" },
  maintenance: { label: "Maintenance", tone: "warning" },
};

export const VISITOR_STATUS_META: Record<VisitorStatus, { label: string; tone: Tone }> = {
  pending: { label: "Pending", tone: "warning" },
  approved: { label: "Approved", tone: "info" },
  rejected: { label: "Rejected", tone: "danger" },
  checked_in: { label: "Checked in", tone: "success" },
  checked_out: { label: "Checked out", tone: "neutral" },
  expired: { label: "Expired", tone: "neutral" },
  cancelled: { label: "Cancelled", tone: "neutral" },
};

export const PERMIT_STATUS_META: Record<PermitStatus, { label: string; tone: Tone }> = {
  pending: { label: "Scheduled", tone: "info" },
  active: { label: "Active", tone: "success" },
  expired: { label: "Expired", tone: "neutral" },
  revoked: { label: "Revoked", tone: "danger" },
};

export const RESIDENT_STATUS_META: Record<ResidentStatus, { label: string; tone: Tone }> = {
  active: { label: "Active", tone: "success" },
  inactive: { label: "Inactive", tone: "neutral" },
  moved_out: { label: "Moved out", tone: "neutral" },
};

export const VEHICLE_STATUS_META: Record<VehicleStatus, { label: string; tone: Tone }> = {
  active: { label: "Active", tone: "success" },
  suspended: { label: "Suspended", tone: "danger" },
  inactive: { label: "Inactive", tone: "neutral" },
};

export const BLACKLIST_TYPE_META: Record<
  BlacklistEntryType,
  { label: string; tone: Tone }
> = {
  plate: { label: "Plate", tone: "danger" },
  face: { label: "Face", tone: "warning" },
  person: { label: "Person", tone: "warning" },
};

export const DEMO_ACCOUNTS = [
  {
    role: "Administrator",
    email: "admin@gatevision.app",
    password: "Admin@12345",
    description: "Full access, analytics, users and configuration",
  },
  {
    role: "Security officer",
    email: "officer@gatevision.app",
    password: "Officer@12345",
    description: "Live gate operations, visitors, permits and overrides",
  },
  {
    role: "Resident",
    email: "ahmed@gatevision.app",
    password: "Resident@12345",
    description: "Own profile, vehicles, visitor requests and access history",
  },
];

export const REASON_LABELS: Record<string, string> = {
  registered_vehicle: "Registered vehicle",
  registered_vehicle_with_face: "Registered vehicle + face",
  vehicle_suspended: "Vehicle suspended",
  vehicle_inactive: "Vehicle inactive",
  resident_inactive: "Resident inactive",
  vehicle_owner_mismatch: "Vehicle owner mismatch",
  visitor_permit: "Visitor permit",
  permit_expired: "Permit expired",
  permit_revoked: "Permit revoked",
  permit_not_started: "Permit not started",
  permit_exhausted: "Permit entry limit reached",
  visitor_status_invalid: "Visitor status invalid",
  blacklist_plate: "Blacklisted plate",
  blacklist_face: "Blacklisted face",
  face_matched_resident: "Face matched resident",
  known_face_unknown_vehicle: "Known face, unknown vehicle",
  unknown_plate: "Unknown plate",
  visitor_vehicle_without_permit: "Visitor vehicle without permit",
  registered_exit: "Registered exit",
  no_detection: "No detection",
  manual_override: "Manual override",
};

export function reasonLabel(code: string | null | undefined): string {
  if (!code) return "Unknown";
  return REASON_LABELS[code] ?? code.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export const PAGE_SIZES = [10, 25, 50, 100];
