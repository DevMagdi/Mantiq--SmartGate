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
import { useI18n } from "@/i18n";
import {
  DEMO_SCENARIOS,
  analyzeImage,
  fetchActuatorStatus,
  fetchCameraHealth,
  fetchCvStatus,
  testActuator,
} from "@/services/cv";
import { gateCommand, listGates } from "@/services/admin";
import {
  listAccessLogs,
  overrideAccessLog,
} from "@/services/access";
import { apiErrorMessage, mediaUrl } from "@/services/api";
import type { DetectionStreamPayload, StreamEvent } from "@/types/api";
import type {
  AccessDecision,
  AccessLog,
  ActuatorStatusEntry,
  VisionAnalyzeResult,
} from "@/types/models";
import { DECISION_META, reasonLabel } from "@/utils/constants";
import { formatPercent, formatTime, relativeTime } from "@/utils/format";

const STATUS_TONE: Record<ConnectionStatus, "success" | "warning" | "danger" | "neutral"> = {
  open: "success",
  connecting: "warning",
  reconnecting: "warning",
  closed: "danger",
};

const STATUS_KEY: Record<ConnectionStatus, string> = {
  open: "live.stream",
  connecting: "live.connecting",
  reconnecting: "live.reconnecting",
  closed: "live.disconnected",
};

const DECISION_FILTERS: AccessDecision[] = ["allow", "review", "deny", "unknown"];

export function LiveMonitorPage(): JSX.Element {
  const queryClient = useQueryClient();
  const toast = useToast();
  const fileInput = useRef<HTMLInputElement | null>(null);

  const { t } = useI18n();
  const [gateFilter, setGateFilter] = useState("");
  const [decisionFilter, setDecisionFilter] = useState<AccessDecision | "">("");
  const [plateQuery, setPlateQuery] = useState("");
  const [snapshotsOnly, setSnapshotsOnly] = useState(false);
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
  const actuators = useQuery({
    queryKey: ["cv-actuators"],
    queryFn: () => fetchActuatorStatus(),
    refetchInterval: 30_000,
    retry: false,
  });
  const actuator: ActuatorStatusEntry | undefined = actuators.data?.compounds[0];
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

  const source = paused ? frozen : events;
  const displayed = useMemo(() => {
    const needle = plateQuery.trim().toUpperCase();
    return source.filter((event) => {
      const payload = event.payload as DetectionStreamPayload;
      if (decisionFilter && (payload.decision ?? "unknown") !== decisionFilter) return false;
      if (needle && !(payload.plate_text ?? "").toUpperCase().includes(needle)) return false;
      if (snapshotsOnly && !(payload.snapshot_url || payload.face_snapshot_url)) return false;
      return true;
    });
  }, [source, decisionFilter, plateQuery, snapshotsOnly]);

  const filtersActive = Boolean(decisionFilter || plateQuery || snapshotsOnly);

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

  const testActuatorMutation = useMutation({
    mutationFn: ({ gateId, action }: { gateId: string; action: "open" | "close" | "hold" }) =>
      testActuator(gateId, action),
    onSuccess: (result) => {
      if (result.accepted) {
        toast.success(
          `${result.driver} · ${result.action} ${t("live.actuator_accepted")}`,
          `${result.detail} (${result.latency_ms} ms)`,
        );
      } else {
        toast.error(t("live.actuator_failed"), result.detail);
      }
      void queryClient.invalidateQueries({ queryKey: ["cv-actuators"] });
    },
    onError: (error) => toast.error(t("live.actuator_failed"), apiErrorMessage(error)),
  });

  const analyzeMutation = useMutation({
    mutationFn: async () => {
      if (!analysisFile) throw new Error(t("live.analyse_no_file"));
      if (!analysisGate && !gates[0]) throw new Error(t("live.analyse_no_gate"));
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
        eyebrow={t("live.eyebrow")}
        title={t("live.title")}
        subtitle={t("live.subtitle")}
        actions={
          <>
            <Badge tone={STATUS_TONE[status]} dot className="h-9 px-3">
              {t(STATUS_KEY[status])}
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
              {paused ? t("live.resume") : t("live.pause")}
            </Button>
            <Button variant="ghost" size="md" icon="refresh" onClick={() => void queryClient.invalidateQueries({ queryKey: ["access-logs"] })}>
              {t("live.sync")}
            </Button>
          </>
        }
      />

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard
          label={t("live.cameras_online")}
          value={`${metrics.online}/${metrics.total}`}
          icon="camera"
          tone="success"
          hint={t("live.cameras_hint")}
        />
        <StatCard
          label={t("live.awaiting")}
          value={metrics.pending}
          icon="alert"
          tone={metrics.pending > 0 ? "warning" : "neutral"}
          hint={t("live.awaiting_hint")}
        />
        <StatCard
          label={t("live.engine")}
          value={cvStatus.data?.mode ?? "—"}
          icon="sparkles"
          tone="info"
          hint={cvStatus.data?.engine_ready ? t("live.engine_ready") : t("live.engine_warming")}
        />
        <StatCard
          label={t("live.events")}
          value={displayed.length}
          icon="live"
          tone="brand"
          hint={
            lastEventAt
              ? t("live.last_event", { time: relativeTime(lastEventAt) })
              : t("live.waiting")
          }
        />
      </div>

      <div className="grid gap-4 xl:grid-cols-3">
        <div className="space-y-4 xl:col-span-2">
          <Card>
            <CardHeader
              title={t("live.feed_title")}
              subtitle={t("live.feed_subtitle")}
              icon="live"
              actions={
                <div className="flex items-center gap-2">
                  <select
                    value={gateFilter}
                    onChange={(event) => setGateFilter(event.target.value)}
                    className="focus-ring h-9 rounded-lg border border-ink-200 bg-white px-2 text-xs dark:border-ink-700 dark:bg-ink-900"
                    aria-label={t("live.filter_gate")}
                  >
                    <option value="">{t("live.all_gates")}</option>
                    {gates.map((gate) => (
                      <option key={gate.id} value={gate.id}>{gate.name}</option>
                    ))}
                  </select>
                  <Button variant="ghost" size="sm" onClick={clear}>{t("live.clear")}</Button>
                </div>
              }
            />
            <div className="flex flex-wrap items-center gap-2 border-b border-ink-50 px-4 py-2.5 dark:border-ink-800/60">
              <div className="flex flex-wrap items-center gap-1" role="group" aria-label={t("live.filter_decision")}>
                <FilterChip
                  active={decisionFilter === ""}
                  onClick={() => setDecisionFilter("")}
                  label={t("decision.all")}
                />
                {DECISION_FILTERS.map((value) => (
                  <FilterChip
                    key={value}
                    active={decisionFilter === value}
                    onClick={() => setDecisionFilter(value)}
                    label={t(`decision.${value}`)}
                    tone={DECISION_META[value].tone}
                  />
                ))}
              </div>
              <div className="ms-auto flex flex-1 items-center gap-2 sm:flex-none">
                <input
                  value={plateQuery}
                  onChange={(event) => setPlateQuery(event.target.value)}
                  placeholder={t("live.search_plate")}
                  aria-label={t("live.search_plate")}
                  className="focus-ring h-8 w-full min-w-[120px] rounded-lg border border-ink-200 bg-white px-2 text-xs dark:border-ink-700 dark:bg-ink-900 sm:w-40"
                />
                <label className="flex shrink-0 items-center gap-1.5 text-[11px] text-ink-500 dark:text-ink-400">
                  <input
                    type="checkbox"
                    checked={snapshotsOnly}
                    onChange={(event) => setSnapshotsOnly(event.target.checked)}
                    className="h-3.5 w-3.5 rounded border-ink-300 text-brand-600 focus:ring-brand-500"
                  />
                  {t("live.only_snapshots")}
                </label>
              </div>
            </div>
            <div className="max-h-[560px] divide-y divide-ink-50 overflow-y-auto dark:divide-ink-800/60">
              {displayed.length === 0 ? (
                <div className="flex flex-col items-center justify-center gap-2 px-6 py-16 text-center">
                  <span className="relative grid h-14 w-14 place-items-center rounded-2xl bg-brand-50 text-brand-500 animate-pulse-ring dark:bg-brand-500/10">
                    <Icon name="live" className="h-6 w-6" />
                  </span>
                  <p className="mt-2 text-sm font-semibold">
                    {filtersActive ? t("live.empty_filtered") : t("live.empty_title")}
                  </p>
                  <p className="max-w-sm text-xs leading-relaxed text-ink-500 dark:text-ink-400">
                    {filtersActive
                      ? t("live.empty_filtered")
                      : status === "open"
                        ? t("live.empty_connected")
                        : t("live.empty_disconnected")}
                  </p>
                  {filtersActive ? (
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => {
                        setDecisionFilter("");
                        setPlateQuery("");
                        setSnapshotsOnly(false);
                      }}
                    >
                      {t("live.reset_filters")}
                    </Button>
                  ) : null}
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
              title={t("live.review_queue_title")}
              subtitle={t("live.review_queue_subtitle")}
              icon="shield"
              actions={<Badge tone="warning">{metrics.pending}</Badge>}
            />
            {reviews.isLoading ? (
              <LoadingBlock label={t("common.loading")} />
            ) : (reviews.data?.items ?? []).length === 0 ? (
              <EmptyState
                icon="check"
                title={t("live.review_queue_empty_title")}
                description={t("live.review_queue_empty_description")}
              />
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
                        <p className="force-ltr font-mono text-xs font-semibold uppercase">
                          {log.plate_number ?? t("live.face_detected")}
                        </p>
                        <p className="truncate text-[11px] text-ink-500 dark:text-ink-400">{log.reason}</p>
                        <p className="text-[10px] text-ink-400">
                          {log.gate?.name ?? t("live.gate")} · {formatTime(log.occurred_at)}
                          {log.face_similarity !== null
                            ? ` · ${t("live.face_similarity", {
                                value: formatPercent(log.face_similarity),
                              })}`
                            : ""}
                        </p>
                      </div>
                      <div className="flex gap-2">
                        <Button size="sm" variant="subtle" onClick={() => openReview(log, "allow")} icon="check">
                          {t("live.allow")}
                        </Button>
                        <Button size="sm" variant="danger" onClick={() => openReview(log, "deny")} icon="x">
                          {t("live.deny")}
                        </Button>
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
            <CardHeader
              title={t("live.barrier_control")}
              subtitle={t("live.barrier_control_subtitle")}
              icon="gate"
            />
            <div className="space-y-3 p-4">
              <Select
                label={t("live.gate")}
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
                  {t("live.open_barrier")}
                </Button>
                <Button
                  variant="outline"
                  onClick={() => commandMutation.mutate({ gateId: activeGateId, action: "close" })}
                  disabled={!activeGateId}
                >
                  {t("live.close_barrier")}
                </Button>
                <Button
                  variant="ghost"
                  onClick={() => commandMutation.mutate({ gateId: activeGateId, action: "hold" })}
                  disabled={!activeGateId}
                >
                  {t("live.hold_barrier")}
                </Button>
              </div>
              <div className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-[11px] leading-relaxed text-amber-800 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-200">
                <Icon name="alert" className="me-1 inline h-3 w-3" />
                {t("live.barrier_warning")}
              </div>
            </div>
          </Card>

          <Card>
            <CardHeader
              title={t("live.actuator_title")}
              subtitle={t("live.actuator_subtitle")}
              icon="sparkles"
            />
            <div className="p-4">
              <div className="rounded-xl border border-ink-200 p-3 dark:border-ink-700">
                <div className="flex items-center justify-between gap-2">
                  <p className="text-[11px] font-semibold uppercase tracking-wide text-ink-400">
                    {t("live.actuator_driver")}
                  </p>
                  <Badge
                    tone={
                      actuator && actuator.health?.ready === false ? "danger" : "success"
                    }
                    dot
                  >
                    {actuator?.driver ?? "—"}
                  </Badge>
                </div>
                <p className="mt-1 text-[11px] text-ink-500 dark:text-ink-400">
                  {actuator && actuator.health?.ready === false
                    ? t("live.actuator_degraded")
                    : t("live.actuator_ready")}
                </p>
                <p className="mt-2 text-[10px] font-semibold uppercase tracking-wide text-ink-400">
                  {t("live.actuator_last")}
                </p>
                {actuator?.recent_commands?.length ? (
                  <p className="mt-0.5 truncate text-[11px] text-ink-600 dark:text-ink-300">
                    {actuator.recent_commands[0].action} ·{" "}
                    {actuator.recent_commands[0].accepted
                      ? t("live.actuator_accepted")
                      : t("live.actuator_failed")}{" "}
                    · {actuator.recent_commands[0].latency_ms} ms ·{" "}
                    {relativeTime(actuator.recent_commands[0].occurred_at)}
                  </p>
                ) : (
                  <p className="mt-0.5 text-[11px] text-ink-400">{t("live.actuator_none")}</p>
                )}
                <Button
                  variant="outline"
                  size="sm"
                  className="mt-2 w-full"
                  icon="refresh"
                  loading={
                    testActuatorMutation.isPending &&
                    testActuatorMutation.variables?.action === "open"
                  }
                  disabled={!activeGateId}
                  onClick={() =>
                    testActuatorMutation.mutate({ gateId: activeGateId, action: "open" })
                  }
                >
                  {t("live.actuator_test")}
                </Button>
              </div>
            </div>
          </Card>

          <Card>
            <CardHeader
              title={t("live.analyse_title")}
              subtitle={
                cvStatus.data?.mode === "mock"
                  ? t("live.analyse_mock_subtitle")
                  : t("live.analyse_real_subtitle")
              }
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
                <label className="field-label">{t("live.frame_label")}</label>
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
              <Select
                label={t("live.scenario_label")}
                value={scenario}
                onChange={(event) => setScenario(event.target.value)}
              >
                <option value="">{t("live.raw_image")}</option>
                {DEMO_SCENARIOS.map((item) => (
                  <option key={item.key} value={item.key}>{t(item.labelKey)}</option>
                ))}
              </Select>
              <Button
                className="w-full"
                icon="sparkles"
                onClick={() => analyzeMutation.mutate()}
                loading={analyzeMutation.isPending}
                disabled={!analysisFile}
              >
                {t("live.run_pipeline")}
              </Button>

              {analysisResult ? (
                <div className="animate-fade-in rounded-xl border border-ink-200 bg-ink-50/60 p-3 dark:border-ink-700 dark:bg-ink-950/40">
                  <div className="flex items-center justify-between">
                    <Badge tone={DECISION_META[analysisResult.decision].tone} dot>
                      {DECISION_META[analysisResult.decision].label}
                    </Badge>
                    <span className="text-[10px] text-ink-400">{analysisResult.processing_ms ?? 0} ms</span>
                  </div>
                  <p className="force-ltr mt-2 font-mono text-sm font-bold uppercase">
                    {analysisResult.plate_text ?? t("live.no_plate")}
                  </p>
                  <p className="text-[11px] text-ink-500 dark:text-ink-400">{analysisResult.reason}</p>
                  <div className="mt-2 grid grid-cols-2 gap-2 text-[10px] text-ink-500 dark:text-ink-400">
                    <span>
                      {t("live.face_matched")}: {analysisResult.face_matched ? t("live.yes") : t("live.no")}
                    </span>
                    <span>
                      {t("live.face_similarity", {
                        value: formatPercent(analysisResult.face_similarity),
                      })}
                    </span>
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
        title={reviewDecision === "allow" ? t("live.confirm_allow") : t("live.confirm_deny")}
        description={reviewTarget ? `${reviewTarget.plate_number ?? "Pedestrian"} · ${reviewTarget.reason}` : undefined}
        footer={
          <>
            <Button variant="outline" onClick={() => setReviewTarget(null)}>{t("live.cancel")}</Button>
            <Button
              variant={reviewDecision === "allow" ? "primary" : "danger"}
              loading={overrideMutation.isPending}
              onClick={() => reviewTarget && overrideMutation.mutate({ logId: reviewTarget.id, decision: reviewDecision })}
            >
              {reviewDecision === "allow" ? t("live.confirm_allow") : t("live.confirm_deny")}
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          <Textarea
            label={t("live.reason")}
            required
            value={reviewReason}
            onChange={(event) => setReviewReason(event.target.value)}
            placeholder={t("live.reason_placeholder")}
          />
          <label className="flex items-center gap-2 text-xs text-ink-600 dark:text-ink-300">
            <input
              type="checkbox"
              checked={reviewOpenGate}
              onChange={(event) => setReviewOpenGate(event.target.checked)}
              disabled={reviewDecision !== "allow"}
              className="h-4 w-4 rounded border-ink-300 text-brand-600 focus:ring-brand-500"
            />
            {t("live.open_gate")}
          </label>
        </div>
      </Modal>

      <Modal
        open={lightbox !== null}
        onClose={() => setLightbox(null)}
        title={lightbox?.title ?? t("dashboard.table.snapshot")}
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
  const { t, reason } = useI18n();
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
          <p className="force-ltr font-mono text-sm font-bold uppercase tracking-wide text-ink-900 dark:text-ink-100">
            {payload.plate_text ?? t("live.face_detected")}
          </p>
          <Badge tone={meta.tone} dot>{t(`decision.${decision}`)}</Badge>
          {payload.direction ? (
            <span className="text-[10px] font-semibold uppercase tracking-wide text-ink-400">{payload.direction}</span>
          ) : null}
          {payload.gate_opened ? (
            <span className="text-[10px] font-semibold text-brand-600 dark:text-brand-400">
              {t("live.barrier_opened")}
            </span>
          ) : decision === "allow" ? (
            <span className="text-[10px] font-semibold text-rose-600 dark:text-rose-400">
              {t("live.barrier_closed")}
            </span>
          ) : null}
        </div>
        <p className="mt-0.5 truncate text-xs text-ink-500 dark:text-ink-400">
          {reason(payload.reason_code, payload.reason ?? reasonLabel(payload.reason_code))}
        </p>
        <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px] text-ink-400">
          <span>{payload.gate_name ?? t("live.gate")}</span>
          <span>{formatTime(payload.occurred_at ?? event.occurred_at)}</span>
          {payload.plate_confidence !== undefined && payload.plate_confidence !== null ? (
            <span>{t("live.plate_confidence", { value: formatPercent(payload.plate_confidence) })}</span>
          ) : null}
          {payload.face_similarity !== null && payload.face_similarity !== undefined ? (
            <span>{t("live.face_similarity", { value: formatPercent(payload.face_similarity) })}</span>
          ) : null}
          {payload.processing_ms ? <span>{payload.processing_ms} ms</span> : null}
        </div>
      </div>

      {isReview ? (
        <div className="flex shrink-0 flex-col justify-center gap-1.5">
          <Button size="sm" variant="subtle" onClick={() => onReview(toAccessLogStub(payload, event), "allow")} icon="check">
            {t("live.allow")}
          </Button>
          <Button size="sm" variant="ghost" onClick={() => onReview(toAccessLogStub(payload, event), "deny")} icon="x">
            {t("live.deny")}
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


function FilterChip({
  active,
  label,
  onClick,
  tone = "neutral",
}: {
  active: boolean;
  label: string;
  onClick: () => void;
  tone?: "success" | "danger" | "warning" | "info" | "neutral" | "brand";
}): JSX.Element {
  const activeTone: Record<string, string> = {
    success: "border-brand-500 bg-brand-50 text-brand-700 dark:bg-brand-500/15 dark:text-brand-300",
    danger: "border-rose-500 bg-rose-50 text-rose-700 dark:bg-rose-500/15 dark:text-rose-300",
    warning: "border-amber-500 bg-amber-50 text-amber-700 dark:bg-amber-500/15 dark:text-amber-300",
    info: "border-sky-500 bg-sky-50 text-sky-700 dark:bg-sky-500/15 dark:text-sky-300",
    brand: "border-brand-500 bg-brand-50 text-brand-700 dark:bg-brand-500/15 dark:text-brand-300",
    neutral: "border-ink-400 bg-ink-100 text-ink-700 dark:bg-ink-800 dark:text-ink-200",
  };
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={cn(
        "focus-ring rounded-full border px-2.5 py-1 text-[11px] font-semibold transition",
        active
          ? activeTone[tone]
          : "border-transparent bg-transparent text-ink-500 hover:bg-ink-100 dark:text-ink-400 dark:hover:bg-ink-800",
      )}
    >
      {label}
    </button>
  );
}
