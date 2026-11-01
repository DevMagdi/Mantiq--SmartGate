import { api } from "@/services/api";
import type { MessageResponse } from "@/types/api";
import type {
  ActuatorStatusResponse,
  ActuatorTestResult,
  VisionAnalyzeResult,
  VisionPipelineStatus,
} from "@/types/models";

export async function fetchCvStatus(): Promise<VisionPipelineStatus> {
  const { data } = await api.get<VisionPipelineStatus>("/cv/status");
  return data;
}

export async function warmupCv(): Promise<VisionPipelineStatus> {
  const { data } = await api.post<VisionPipelineStatus>("/cv/warmup");
  return data;
}

export async function analyzeImage(
  gateId: string,
  file: File,
  demoScenario?: string,
): Promise<VisionAnalyzeResult> {
  const form = new FormData();
  form.append("gate_id", gateId);
  form.append("file", file);
  if (demoScenario) form.append("demo_scenario", demoScenario);
  const { data } = await api.post<VisionAnalyzeResult>("/cv/analyze", form, {
    timeout: 60_000,
  });
  return data;
}

export async function confirmReview(logId: string): Promise<MessageResponse> {
  const { data } = await api.post<MessageResponse>(`/cv/analysis/${logId}/confirm`);
  return data;
}

export async function fetchCameraHealth(): Promise<Record<string, number>> {
  const { data } = await api.get<Record<string, number>>("/cv/camera-health");
  return data;
}

export async function fetchWorkers(): Promise<Record<string, unknown>> {
  const { data } = await api.get<Record<string, unknown>>("/cv/workers");
  return data;
}

export async function fetchActuatorStatus(compoundId?: string): Promise<ActuatorStatusResponse> {
  const { data } = await api.get<ActuatorStatusResponse>("/cv/actuators", {
    params: compoundId ? { compound_id: compoundId } : undefined,
  });
  return data;
}

export async function testActuator(
  gateId: string,
  action: "open" | "close" | "hold" = "open",
): Promise<ActuatorTestResult> {
  const { data } = await api.post<ActuatorTestResult>("/cv/actuators/test", {
    gate_id: gateId,
    action,
  });
  return data;
}

export const DEMO_SCENARIOS: { key: string; label: string; description: string }[] = [
  {
    key: "resident-entry",
    label: "Resident vehicle · allow",
    description: "Registered resident plate arriving at the entry lane.",
  },
  {
    key: "visitor-permit",
    label: "Visitor with permit · allow",
    description: "Visitor plate covered by an active temporary permit.",
  },
  {
    key: "unknown-vehicle",
    label: "Unknown plate · unknown",
    description: "Plate that is not registered anywhere in the compound.",
  },
  {
    key: "blacklisted-plate",
    label: "Blacklisted plate · deny",
    description: "Plate present on the active blacklist.",
  },
  {
    key: "resident-pedestrian",
    label: "Resident face · allow",
    description: "Pedestrian lane face match against the resident gallery.",
  },
  {
    key: "blocked-person",
    label: "Blacklisted face · deny",
    description: "Face matching a person blocked by security.",
  },
  {
    key: "known-face-unknown-car",
    label: "Known face, unknown car · review",
    description: "Recognised resident in an unregistered vehicle.",
  },
  {
    key: "suspended-resident",
    label: "Suspended resident · deny",
    description: "Resident vehicle with access suspended.",
  },
];
