import { useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Icon } from "@/components/Icon";
import { PageHeader } from "@/components/PageHeader";
import { StatCard } from "@/components/StatCard";
import {
  Badge,
  Button,
  Card,
  CardHeader,
  EmptyState,
  LoadingBlock,
  Modal,
  Select,
  Textarea,
  cn,
} from "@/components/ui";
import { useGateEvents, type ConnectionStatus } from "@/hooks/useGateEvents";
import { useToast } from "@/hooks/useToast";
import { analyzeImage, fetchCameraHealth, fetchCvStatus } from "@/services/cv";
import { gateCommand, listGates } from "@/services/admin";
import {
  listAccessLogs,
  overrideAccessLog,
} from "@/services/access";
import { apiErrorMessage, mediaUrl } from "@/services/api";
import type { DetectionStreamPayload, StreamEvent } from "@/types/api";
import type { AccessDecision, AccessLog, VisionAnalyzeResult } from "@/types/models";
import { DEMO_SCENARIOS } from "@/services/cv";
import { DECISION_META } from "@/utils/constants";
import { formatPercent, formatTime, relativeTime } from "@/utils/format";

const STATUS_META: Record<ConnectionStatus, { tone: "success" | "warning" | "danger" | "neutral"; label: string }> = {
  open: { tone: "success", label: "Live stream" },
  connecting: { tone: "warning", label: "Connecting" },
  reconnecting: { tone: "warning", label: "Reconnecting" },
  closed: { tone: "danger", label: "Disconnected" },
};

export function LiveMonitorPage(): JSX.Element {
  const queryClient = useQueryClient();
  const toast = useToast();
  const fileInput = useRef<HTMLInputElement | null>(null);

  const [gateFilter, setGateFilter] = useState("");
  const [controlGateId, setControlGateId] = useState("");
  const [paused, setPaused] = useState(false);
  const [frozen, setFrozen] = useState<StreamEvent[]>([]);
  const [lightbox, setLightbox] = useState<{ url: string; title: string } | null>(null);
  const [reviewTarget, setReviewTarget] = useState<AccessLog | null>(null);
  const [reviewDecision, setReviewDecision] = useState<AccessDecision>("allow");
  const [reviewReason, setReviewReason] = useState("Verified by the security officer");
  const [reviewOpenGate, setReviewOpenGate] = useState(true);

  const [analysisGate, setAnalysisGate] = useState("");
  const [analysisFile, setAnalysisFile] = useState<File | null>(null);
  const [scenario, setScenario] = useState("");
  const [analysisResult, setAnalysisResult] = useState<VisionAnalyzeResult | null>(null);

  const gatesQuery = useQuery({ queryKey: ["gates"], queryFn: () => listGates() });
  const gates = gatesQuery.data?.items ?? [];
  const activeGateId = controlGateId || gates[0]?.id || "";

  const cvStatus = useQuery({ queryKey: ["cv-status"], queryFn: fetchCvStatus, retry: false });
  const cameraHealth = useQuery({
    queryKey: ["camera-health"],
    queryFn: fetchCameraHealth,
    refetchInterval: 30_000,
  });
  const reviews = useQuery({
    queryKey: ["access-logs", "review-queue"],
    queryFn: () => listAccessLogs({ requires_review: true, page_size: 25 }),
    refetchInterval: 20_000,
  });

  const { events, status, lastEventAt, clear } = useGateEvents({
    gateId: gateFilter || undefined,
    onEvent: (event: StreamEvent) => {
      if (event.type === "detection.created" || event.type === "access.decision" || event.type === "access.override") {
        void queryClient.invalidateQueries({ queryKey: ["access-logs"] });
        void queryClient.invalidateQueries({ queryKey: ["dashboard"] });
      }
      if (event.type === "gate.status" || event.type === "gate.status.override") {
        void queryClient.invalidateQueries({ queryKey: ["gates"] });
      }
      if (event.type === "camera.status") {
        void queryClient.invalidateQueries({ queryKey: ["camera-health"] });
      }
    },
  });

  const displayed = paused ? frozen : events;

  const commandMutation = useMutation({
    mutationFn: ({ gateId, action }: { gateId: string; action: "open" | "close" | "hold" }) =>
      gateCommand(gateId, action, "Issued from the live gate monitor"),
    onSuccess: (result, variables) => {
      toast.success(`Gate ${variables.action} command accepted`, result.detail);
      void queryClient.invalidateQueries({ queryKey: ["gates"] });
    },
    onError: (error) => toast.error("Gate command failed", apiErrorMessage(error)),
  });

  const overrideMutation = useMutation({
    mutationFn: ({ logId, decision }: { logId: string; decision: AccessDecision }) =>
      overrideAccessLog(logId, {
        decision,
        reason: reviewReason,
        open_gate: reviewOpenGate && decision === "allow",
        notes: "Resolved from the live monitor",
      }),
    onSuccess: (log) => {
      toast.success(`Decision updated to ${log.decision}`, log.reason);
      setReviewTarget(null);
      void queryClient.invalidateQueries({ queryKey: ["access-logs"] });
      void queryClient.invalidateQueries({ queryKey: ["dashboard"] });
    },
    onError: (error) => toast.error("Override failed", apiErrorMessage(error)),
  });

  const analyzeMutation = useMutation({
    mutationFn: async () => {
      if (!analysisFile) throw new Error("Choose an image to analyse");
      if (!analysisGate && !gates[0]) throw new Error("Select a gate");
      return analyzeImage(analysisGate || gates[0].id, analysisFile, scenario || undefined);
    },
    onSuccess: (result) => {
      setAnalysisResult(result);
      toast.success(`Analysis complete · ${result.decision.toUpperCase()}`, result.reason);
      void queryClient.invalidateQueries({ queryKey: ["access-logs"] });
      void queryClient.invalidateQueries({ queryKey: ["dashboard"] });
    },
    onError: (error) => toast.error("Analysis failed", apiErrorMessage(error)),
  });

  const metrics = useMemo(
    () => ({
      online: cameraHealth.data?.online ?? 0,
      total: cameraHealth.data?.total ?? 0,
      pending: reviews.data?.total ?? 0,
    }),
    [cameraHealth.data, reviews.data],
  );

  const openReview = (log: AccessLog, decision: AccessDecision): void => {
    setReviewTarget(log);
    setReviewDecision(decision);
    setReviewReason(decision === "allow" ? "Verified by the security officer" : "Access refused after review");
    setReviewOpenGate(decision === "allow");
  };

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Realtime operations"
        title="Live gate monitor"
        subtitle="Watch every plate and face decision as it happens, clear manual reviews and control the barriers."
        actions={
          <>
            <Badge tone={STATUS_META[status].tone} dot className="h-9 px-3">
              {STATUS_META[status].label}
            </Badge>
            <Button
              variant="outline"
              size="md"
              icon={paused ? "play" : "pause"}
              onClick={() => {
                if (!paused) setFrozen(events);
                setPaused((current) => !current);
              }}
            >
              {paused ? "Resume feed" : "Pause feed"}
            </Button>
            <Button variant="ghost" size="md" icon="refresh" onClick={() => void queryClient.invalidateQueries({ queryKey: ["access-logs"] })}>
              Sync
            </Button>
          </>
        }
      />

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard label="Cameras online" value={`${metrics.online}/${metrics.total}`} icon="camera" tone="success" hint="Streams reporting frames" />
        <StatCard label="Awaiting review" value={metrics.pending} icon="alert" tone={metrics.pending > 0 ? "warning" : "neutral"} hint="Decisions needing an officer" />
        <StatCard label="Vision engine" value={cvStatus.data?.mode ?? "—"} icon="sparkles" tone="info" hint={cvStatus.data?.engine_ready ? "Models ready" : "Warming up"} />
        <StatCard label="Events in feed" value={displayed.length} icon="live" tone="brand" hint={lastEventAt ? `Last event ${relativeTime(lastEventAt)}` : "Waiting for detections"} />
      </div>

      <div className="grid gap-4 xl:grid-cols-3">
        <div className="space-y-4 xl:col-span-2">
          <Card>
            <CardHeader
              title="Detection stream"
              subtitle="Plate, face and combined decisions published over WebSocket"
              icon="live"
              actions={
                <div className="flex items-center gap-2">
                  <select
                    value={gateFilter}
                    onChange={(event) => setGateFilter(event.target.value)}
                    className="focus-ring h-9 rounded-lg border border-ink-200 bg-white px-2 text-xs dark:border-ink-700 dark:bg-ink-900"
                    aria-label="Filter by gate"
                  >
                    <option value="">All gates</option>
                    {gates.map((gate) => (
                      <option key={gate.id} value={gate.id}>{gate.name}</option>
                    ))}
                  </select>
                  <Button variant="ghost" size="sm" onClick={clear}>Clear</Button>
                </div>
              }
            />
            <div className="max-h-[560px] divide-y divide-ink-50 overflow-y-auto dark:divide-ink-800/60">
              {displayed.length === 0 ? (
                <div className="flex flex-col items-center justify-center gap-2 px-6 py-16 text-center">
                  <span className="relative grid h-14 w-14 place-items-center rounded-2xl bg-brand-50 text-brand-500 animate-pulse-ring dark:bg-brand-500/10">
                    <Icon name="live" className="h-6 w-6" />
                  </span>
                  <p className="mt-2 text-sm font-semibold">Listening for gate events…</p>
                  <p className="max-w-sm text-xs leading-relaxed text-ink-500 dark:text-ink-400">
                    {status === "open"
                      ? "Detections will appear here the moment a camera publishes a plate or a face."
                      : "The realtime stream is disconnected. Retrying automatically…"}
                  </p>
                </div>
              ) : (
                displayed.map((event) => (
                  <FeedItem key={event.id} event={event} onOpenImage={setLightbox} onReview={openReview} />
                ))
              )}
            </div>
          </Card>

          <Card>
            <CardHeader
              title="Manual review queue"
              subtitle="Low-confidence or ambiguous detections that need a human decision"
              icon="shield"
              actions={<Badge tone="warning">{metrics.pending} pending</Badge>}
            />
            {reviews.isLoading ? (
              <LoadingBlock label="Loading review queue…" />
            ) : (reviews.data?.items ?? []).length === 0 ? (
              <EmptyState icon="check" title="Queue is clear" description="Every detection in this compound has been resolved." />
            ) : (
              <div className="divide-y divide-ink-50 dark:divide-ink-800/60">
                {(reviews.data?.items ?? []).map((log) => {
                  const snapshot = mediaUrl(log.snapshot_url ?? log.face_snapshot_url);
                  return (
                    <div key={log.id} className="flex flex-wrap items-center gap-3 px-4 py-3">
                      {snapshot ? (
                        <img src={snapshot} alt="Review snapshot" className="h-12 w-20 rounded-lg border border-ink-200 object-cover dark:border-ink-700" />
                      ) : (
                        <div className="grid h-12 w-20 place-items-center rounded-lg bg-ink-100 text-ink-400 dark:bg-ink-800">
                          <Icon name="camera" className="h-4 w-4" />
                        </div>
                      )}
                      <div className="min-w-0 flex-1">
                        <p className="font-mono text-xs font-semibold uppercase">{log.plate_number ?? "Face only"}</p>
                        <p className="truncate text-[11px] text-ink-500 dark:text-ink-400">{log.reason}</p>
                        <p className="text-[10px] text-ink-400">
                          {log.gate?.name ?? "Gate"} · {formatTime(log.occurred_at)}
                          {log.face_similarity !== null ? ` · face ${formatPercent(log.face_similarity)}` : ""}
                        </p>
                      </div>
                      <div className="flex gap-2">
                        <Button size="sm" variant="subtle" onClick={() => openReview(log, "allow")} icon="check">Allow</Button>
                        <Button size="sm" variant="danger" onClick={() => openReview(log, "deny")} icon="x">Deny</Button>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </Card>
        </div>

        <div className="space-y-4">
          <Card>
            <CardHeader title="Barrier control" subtitle="Direct gate commands are audited" icon="gate" />
            <div className="space-y-3 p-4">
              <Select
                label="Gate"
                value={activeGateId}
                onChange={(event) => setControlGateId(event.target.value)}
              >
                {gates.map((gate) => (
                  <option key={gate.id} value={gate.id}>
                    {gate.name} · {gate.code}
                  </option>
                ))}
              </Select>
              <div className="grid grid-cols-3 gap-2">
                <Button
                  variant="primary"
                  onClick={() => commandMutation.mutate({ gateId: activeGateId, action: "open" })}
                  loading={commandMutation.isPending && commandMutation.variables?.action === "open"}
                  disabled={!activeGateId}
                >
                  Open
                </Button>
                <Button
                  variant="outline"
                  onClick={() => commandMutation.mutate({ gateId: activeGateId, action: "close" })}
                  disabled={!activeGateId}
                >
                  Close
                </Button>
                <Button
                  variant="ghost"
                  onClick={() => commandMutation.mutate({ gateId: activeGateId, action: "hold" })}
                  disabled={!activeGateId}
                >
                  Hold
                </Button>
              </div>
              <div className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-[11px] leading-relaxed text-amber-800 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-200">
                <Icon name="alert" className="mr-1 inline h-3 w-3" />
                Only open the barrier after confirming the driver identity.
              </div>
            </div>
          </Card>

          <Card>
            <CardHeader
              title="Analyse an image"
              subtitle={cvStatus.data?.mode === "mock" ? "Demo mode replays scripted scenarios" : "Run a captured frame through the pipeline"}
              icon="upload"
              actions={<Badge tone="info">{cvStatus.data?.mode ?? "—"}</Badge>}
            />
            <div className="space-y-3 p-4">
              <Select label="Gate" value={analysisGate || gates[0]?.id || ""} onChange={(event) => setAnalysisGate(event.target.value)}>
                {gates.map((gate) => (
                  <option key={gate.id} value={gate.id}>{gate.name}</option>
                ))}
              </Select>
              <div>
                <label className="field-label">Frame (JPEG / PNG)</label>
                <input
                  ref={fileInput}
                  type="file"
                  accept="image/*"
                  onChange={(event) => setAnalysisFile(event.target.files?.[0] ?? null)}
                  className="block w-full cursor-pointer rounded-xl border border-dashed border-ink-300 bg-ink-50/60 px-3 py-3 text-xs text-ink-500 file:mr-3 file:rounded-lg file:border-0 file:bg-brand-50 file:px-2.5 file:py-1.5 file:text-xs file:font-semibold file:text-brand-700 dark:border-ink-700 dark:bg-ink-950/40 dark:text-ink-400 dark:file:bg-brand-500/10 dark:file:text-brand-300"
                />
                {analysisFile ? (
                  <p className="mt-1 truncate text-[10px] text-ink-400">{analysisFile.name}</p>
                ) : null}
              </div>
              <Select label="Demo scenario (mock engine)" value={scenario} onChange={(event) => setScenario(event.target.value)}>
                <option value="">Use raw image</option>
                {DEMO_SCENARIOS.map((item) => (
                  <option key={item.key} value={item.key}>{item.label}</option>
                ))}
              </Select>
              <Button className="w-full" icon="sparkles" onClick={() => analyzeMutation.mutate()} loading={analyzeMutation.isPending} disabled={!analysisFile}>
                Run pipeline
              </Button>

              {analysisResult ? (
                <div className="animate-fade-in rounded-xl border border-ink-200 bg-ink-50/60 p-3 dark:border-ink-700 dark:bg-ink-950/40">
                  <div className="flex items-center justify-between">
                    <Badge tone={DECISION_META[analysisResult.decision].tone} dot>
                      {DECISION_META[analysisResult.decision].label}
                    </Badge>
                    <span className="text-[10px] text-ink-400">{analysisResult.processing_ms ?? 0} ms</span>
                  </div>
                  <p className="mt-2 font-mono text-sm font-bold uppercase">{analysisResult.plate_text ?? "No plate"}</p>
                  <p className="text-[11px] text-ink-500 dark:text-ink-400">{analysisResult.reason}</p>
                  <div className="mt-2 grid grid-cols-2 gap-2 text-[10px] text-ink-500 dark:text-ink-400">
                    <span>Face matched: {analysisResult.face_matched ? "yes" : "no"}</span>
                    <span>Similarity: {formatPercent(analysisResult.face_similarity)}</span>
                  </div>
                  {analysisResult.plate_snapshot_url ? (
                    <img
                      src={mediaUrl(analysisResult.plate_snapshot_url) ?? undefined}
                      alt="Analysed frame"
                      className="mt-2 w-full rounded-lg border border-ink-200 object-cover dark:border-ink-700"
                    />
                  ) : null}
                </div>
              ) : null}
            </div>
          </Card>
        </div>
      </div>

      <Modal
        open={reviewTarget !== null}
        onClose={() => setReviewTarget(null)}
        title={reviewDecision === "allow" ? "Allow entry" : "Refuse entry"}
        description={reviewTarget ? `${reviewTarget.plate_number ?? "Pedestrian"} · ${reviewTarget.reason}` : undefined}
        footer={
          <>
            <Button variant="outline" onClick={() => setReviewTarget(null)}>Cancel</Button>
            <Button
              variant={reviewDecision === "allow" ? "primary" : "danger"}
              loading={overrideMutation.isPending}
              onClick={() => reviewTarget && overrideMutation.mutate({ logId: reviewTarget.id, decision: reviewDecision })}
            >
              {reviewDecision === "allow" ? "Confirm allow" : "Confirm denial"}
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          <Textarea
            label="Reason"
            required
            value={reviewReason}
            onChange={(event) => setReviewReason(event.target.value)}
            placeholder="Explain the decision for the audit trail"
          />
          <label className="flex items-center gap-2 text-xs text-ink-600 dark:text-ink-300">
            <input
              type="checkbox"
              checked={reviewOpenGate}
              onChange={(event) => setReviewOpenGate(event.target.checked)}
              disabled={reviewDecision !== "allow"}
              className="h-4 w-4 rounded border-ink-300 text-brand-600 focus:ring-brand-500"
            />
            Open the barrier after approval
          </label>
        </div>
      </Modal>

      <Modal
        open={lightbox !== null}
        onClose={() => setLightbox(null)}
        title={lightbox?.title ?? "Snapshot"}
        size="lg"
      >
        {lightbox ? (
          <img src={lightbox.url} alt={lightbox.title} className="w-full rounded-xl border border-ink-200 dark:border-ink-700" />
        ) : null}
      </Modal>
    </div>
  );
}

function FeedItem({
  event,
  onOpenImage,
  onReview,
}: {
  event: StreamEvent;
  onOpenImage: (payload: { url: string; title: string }) => void;
  onReview: (log: AccessLog, decision: AccessDecision) => void;
}): JSX.Element {
  const payload = event.payload as DetectionStreamPayload;
  const decision = (payload.decision ?? "unknown") as AccessDecision;
  const meta = DECISION_META[decision] ?? DECISION_META.unknown;
  const snapshot = mediaUrl(payload.snapshot_url ?? payload.face_snapshot_url);
  const isReview = event.type === "detection.created" && decision === "review" && Boolean(payload.access_log_id);

  return (
    <div className="flex gap-3 px-4 py-3.5 transition hover:bg-ink-50/60 dark:hover:bg-ink-800/20">
      <button
        type="button"
        onClick={() => snapshot && onOpenImage({ url: snapshot, title: payload.plate_text ?? "Gate snapshot" })}
        className={cn(
          "group relative h-[64px] w-[96px] shrink-0 overflow-hidden rounded-lg border border-ink-200 bg-ink-100 dark:border-ink-700 dark:bg-ink-800",
          !snapshot && "cursor-default",
        )}
      >
        {snapshot ? (
          <img src={snapshot} alt="Detection" className="h-full w-full object-cover transition group-hover:scale-105" loading="lazy" />
        ) : (
          <span className="grid h-full w-full place-items-center text-ink-400">
            <Icon name="camera" className="h-4 w-4" />
          </span>
        )}
      </button>

      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <p className="font-mono text-sm font-bold uppercase tracking-wide text-ink-900 dark:text-ink-100">
            {payload.plate_text ?? "Face detected"}
          </p>
          <Badge tone={meta.tone} dot>{meta.label}</Badge>
          {payload.direction ? (
            <span className="text-[10px] font-semibold uppercase tracking-wide text-ink-400">{payload.direction}</span>
          ) : null}
          {payload.gate_opened ? (
            <span className="text-[10px] font-semibold text-brand-600 dark:text-brand-400">barrier opened</span>
          ) : null}
        </div>
        <p className="mt-0.5 truncate text-xs text-ink-500 dark:text-ink-400">{payload.reason}</p>
        <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px] text-ink-400">
          <span>{payload.gate_name ?? "Gate"}</span>
          <span>{formatTime(payload.occurred_at ?? event.occurred_at)}</span>
          {payload.plate_confidence !== undefined && payload.plate_confidence !== null ? (
            <span>plate {formatPercent(payload.plate_confidence)}</span>
          ) : null}
          {payload.face_similarity !== null && payload.face_similarity !== undefined ? (
            <span>face {formatPercent(payload.face_similarity)}</span>
          ) : null}
          {payload.processing_ms ? <span>{payload.processing_ms} ms</span> : null}
        </div>
      </div>

      {isReview ? (
        <div className="flex shrink-0 flex-col justify-center gap-1.5">
          <Button size="sm" variant="subtle" onClick={() => onReview(toAccessLogStub(payload, event), "allow")} icon="check">
            Allow
          </Button>
          <Button size="sm" variant="ghost" onClick={() => onReview(toAccessLogStub(payload, event), "deny")} icon="x">
            Deny
          </Button>
        </div>
      ) : null}
    </div>
  );
}

/**
 * The live payload contains everything the review dialog needs, but the
 * override endpoint works with a full access log. We keep a minimal shim so
 * the officer can act without a round-trip; the row is refetched after.
 */
function toAccessLogStub(payload: DetectionStreamPayload, event: StreamEvent): AccessLog {
  const now = new Date().toISOString();
  return {
    id: payload.access_log_id ?? "",
    compound_id: "",
    gate_id: payload.gate_id ?? "",
    camera_id: null,
    direction: (payload.direction as AccessLog["direction"]) ?? "entry",
    occurred_at: payload.occurred_at ?? event.occurred_at,
    decision: (payload.decision as AccessDecision) ?? "review",
    reason_code: payload.reason_code ?? "",
    reason: payload.reason ?? "",
    access_method: (payload.method as AccessLog["access_method"]) ?? "combined",
    plate_number: payload.plate_text ?? null,
    plate_confidence: payload.plate_confidence ?? null,
    face_similarity: payload.face_similarity ?? null,
    vehicle_id: null,
    resident_id: null,
    visitor_id: null,
    permit_id: null,
    snapshot_url: payload.snapshot_url ?? null,
    face_snapshot_url: payload.face_snapshot_url ?? null,
    gate_opened: Boolean(payload.gate_opened),
    is_overridden: false,
    override_by_id: null,
    override_reason: null,
    overridden_at: null,
    notes: null,
    created_at: now,
    gate: null,
    camera: null,
    vehicle: null,
    resident: null,
    visitor: null,
    permit: null,
  };
}
