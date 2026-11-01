/**
 * Compound policy editor — thresholds, decision switches and the barrier driver.
 *
 * Backed by `GET/PATCH /compounds/{id}/settings`. The API returns the *effective*
 * policy (defaults merged with the stored document) plus the defaults, so the
 * panel can show "default: …" hints without duplicating any constant here.
 *
 * Secrets (webhook HMAC, MQTT password) arrive masked as `********`; they are
 * only sent back when the operator explicitly rotates them, which keeps a
 * read-modify-write from wiping the stored credential.
 */
import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Icon } from "@/components/Icon";
import {
  Badge,
  Button,
  Card,
  CardHeader,
  EmptyState,
  Field,
  Input,
  LoadingBlock,
  Select,
  SectionTitle,
} from "@/components/ui";
import { useI18n } from "@/i18n";
import { useToast } from "@/hooks/useToast";
import { getCompoundSettings, updateCompoundSettings } from "@/services/admin";
import { apiErrorMessage } from "@/services/api";
import { fetchActuatorStatus } from "@/services/cv";
import type {
  BarrierDriver,
  CompoundPolicy,
  CompoundSettingsPatch,
} from "@/types/models";
import { formatDateTime } from "@/utils/format";

/* ------------------------------------------------------------------ draft */

interface DraftBarrier {
  driver: BarrierDriver;
  simulator_latency_ms: string;
  simulator_failure_rate: string;
  webhook: {
    url: string;
    secret: string;
    timeout_seconds: string;
    retries: string;
    verify_tls: boolean;
  };
  mqtt: {
    host: string;
    port: string;
    topic: string;
    qos: string;
    username: string;
    password: string;
    tls: boolean;
    simulate: boolean;
  };
  gpio: {
    open_pin: string;
    close_pin: string;
    hold_pin: string;
    active_high: boolean;
    pulse_seconds: string;
    backend: string;
    simulate: boolean;
  };
}

interface Draft {
  vision: Record<
    | "plate_confidence_threshold"
    | "ocr_min_confidence"
    | "face_similarity_threshold"
    | "face_min_quality"
    | "face_min_resolution"
    | "face_min_blur"
    | "face_min_brightness"
    | "face_max_brightness"
    | "face_min_face_ratio"
    | "max_embeddings_per_resident"
    | "duplicate_similarity_threshold",
    string
  > & { reject_duplicate_enrollment: boolean };
  access: {
    auto_open_barrier: boolean;
    allow_face_only_entry: boolean;
    unknown_vehicle_decision: "unknown" | "review" | "deny";
    require_face_for_vehicle: boolean;
    exit_grace_minutes: string;
    allow_blacklist_exit: boolean;
    allow_visitor_exit_after_expiry: boolean;
  };
  barrier: DraftBarrier;
}

const DRIVERS: BarrierDriver[] = ["simulator", "webhook", "mqtt", "gpio"];
const MASK = "********";

const text = (value: number | string | null | undefined): string =>
  value === null || value === undefined ? "" : String(value);

const toDraft = (policy: CompoundPolicy): Draft => ({
  vision: {
    plate_confidence_threshold: text(policy.vision.plate_confidence_threshold),
    ocr_min_confidence: text(policy.vision.ocr_min_confidence),
    face_similarity_threshold: text(policy.vision.face_similarity_threshold),
    face_min_quality: text(policy.vision.face_min_quality),
    face_min_resolution: text(policy.vision.face_min_resolution),
    face_min_blur: text(policy.vision.face_min_blur),
    face_min_brightness: text(policy.vision.face_min_brightness),
    face_max_brightness: text(policy.vision.face_max_brightness),
    face_min_face_ratio: text(policy.vision.face_min_face_ratio),
    max_embeddings_per_resident: text(policy.vision.max_embeddings_per_resident),
    duplicate_similarity_threshold: text(policy.vision.duplicate_similarity_threshold),
    reject_duplicate_enrollment: policy.vision.reject_duplicate_enrollment,
  },
  access: {
    auto_open_barrier: policy.access.auto_open_barrier,
    allow_face_only_entry: policy.access.allow_face_only_entry,
    unknown_vehicle_decision: policy.access.unknown_vehicle_decision,
    require_face_for_vehicle: policy.access.require_face_for_vehicle,
    exit_grace_minutes: text(policy.access.exit_grace_minutes),
    allow_blacklist_exit: policy.access.allow_blacklist_exit,
    allow_visitor_exit_after_expiry: policy.access.allow_visitor_exit_after_expiry,
  },
  barrier: {
    driver: policy.barrier.driver,
    simulator_latency_ms: text(policy.barrier.simulator_latency_ms),
    simulator_failure_rate: text(policy.barrier.simulator_failure_rate),
    webhook: {
      url: policy.barrier.webhook.url ?? "",
      secret: "",
      timeout_seconds: text(policy.barrier.webhook.timeout_seconds),
      retries: text(policy.barrier.webhook.retries),
      verify_tls: policy.barrier.webhook.verify_tls,
    },
    mqtt: {
      host: policy.barrier.mqtt.host ?? "",
      port: text(policy.barrier.mqtt.port),
      topic: policy.barrier.mqtt.topic ?? "",
      qos: text(policy.barrier.mqtt.qos),
      username: policy.barrier.mqtt.username ?? "",
      password: "",
      tls: policy.barrier.mqtt.tls,
      simulate: policy.barrier.mqtt.simulate,
    },
    gpio: {
      open_pin: text(policy.barrier.gpio.open_pin),
      close_pin: text(policy.barrier.gpio.close_pin),
      hold_pin: text(policy.barrier.gpio.hold_pin),
      active_high: policy.barrier.gpio.active_high,
      pulse_seconds: text(policy.barrier.gpio.pulse_seconds),
      backend: policy.barrier.gpio.backend,
      simulate: policy.barrier.gpio.simulate,
    },
  },
});

/** Parse a numeric field, falling back to the value currently stored server-side. */
const num = (value: string, fallback: number): number => {
  const parsed = Number(value);
  return value.trim() === "" || !Number.isFinite(parsed) ? fallback : parsed;
};

const int = (value: string, fallback: number): number => Math.round(num(value, fallback));

const buildPatch = (
  draft: Draft,
  current: CompoundPolicy,
  rotate: { webhook: boolean; mqtt: boolean },
): CompoundSettingsPatch => {
  const patch: CompoundSettingsPatch = {
    vision: {
      plate_confidence_threshold: num(draft.vision.plate_confidence_threshold, current.vision.plate_confidence_threshold),
      ocr_min_confidence: num(draft.vision.ocr_min_confidence, current.vision.ocr_min_confidence),
      face_similarity_threshold: num(draft.vision.face_similarity_threshold, current.vision.face_similarity_threshold),
      face_min_quality: num(draft.vision.face_min_quality, current.vision.face_min_quality),
      face_min_resolution: int(draft.vision.face_min_resolution, current.vision.face_min_resolution),
      face_min_blur: num(draft.vision.face_min_blur, current.vision.face_min_blur),
      face_min_brightness: num(draft.vision.face_min_brightness, current.vision.face_min_brightness),
      face_max_brightness: num(draft.vision.face_max_brightness, current.vision.face_max_brightness),
      face_min_face_ratio: num(draft.vision.face_min_face_ratio, current.vision.face_min_face_ratio),
      max_embeddings_per_resident: int(
        draft.vision.max_embeddings_per_resident,
        current.vision.max_embeddings_per_resident,
      ),
      duplicate_similarity_threshold: num(
        draft.vision.duplicate_similarity_threshold,
        current.vision.duplicate_similarity_threshold,
      ),
      reject_duplicate_enrollment: draft.vision.reject_duplicate_enrollment,
    },
    access: {
      auto_open_barrier: draft.access.auto_open_barrier,
      allow_face_only_entry: draft.access.allow_face_only_entry,
      unknown_vehicle_decision: draft.access.unknown_vehicle_decision,
      require_face_for_vehicle: draft.access.require_face_for_vehicle,
      exit_grace_minutes: int(draft.access.exit_grace_minutes, current.access.exit_grace_minutes),
      allow_blacklist_exit: draft.access.allow_blacklist_exit,
      allow_visitor_exit_after_expiry: draft.access.allow_visitor_exit_after_expiry,
    },
    barrier: {
      driver: draft.barrier.driver,
      simulator_latency_ms: int(draft.barrier.simulator_latency_ms, current.barrier.simulator_latency_ms),
      simulator_failure_rate: num(
        draft.barrier.simulator_failure_rate,
        current.barrier.simulator_failure_rate,
      ),
      webhook: {
        url: draft.barrier.webhook.url.trim(),
        timeout_seconds: num(draft.barrier.webhook.timeout_seconds, current.barrier.webhook.timeout_seconds),
        retries: int(draft.barrier.webhook.retries, current.barrier.webhook.retries),
        verify_tls: draft.barrier.webhook.verify_tls,
      },
      mqtt: {
        host: draft.barrier.mqtt.host.trim(),
        port: int(draft.barrier.mqtt.port, current.barrier.mqtt.port),
        topic: draft.barrier.mqtt.topic.trim(),
        qos: int(draft.barrier.mqtt.qos, current.barrier.mqtt.qos),
        username: draft.barrier.mqtt.username.trim() || null,
        tls: draft.barrier.mqtt.tls,
        simulate: draft.barrier.mqtt.simulate,
      },
      gpio: {
        open_pin: int(draft.barrier.gpio.open_pin, current.barrier.gpio.open_pin),
        close_pin: int(draft.barrier.gpio.close_pin, current.barrier.gpio.close_pin),
        hold_pin: draft.barrier.gpio.hold_pin.trim() === "" ? null : int(draft.barrier.gpio.hold_pin, 0),
        active_high: draft.barrier.gpio.active_high,
        pulse_seconds: num(draft.barrier.gpio.pulse_seconds, current.barrier.gpio.pulse_seconds),
        backend: draft.barrier.gpio.backend,
        simulate: draft.barrier.gpio.simulate,
      },
    },
  };
  // Only overwrite a stored secret when the operator asked to rotate it.
  if (rotate.webhook && draft.barrier.webhook.secret.trim()) {
    patch.barrier!.webhook!.secret = draft.barrier.webhook.secret.trim();
  }
  if (rotate.mqtt && draft.barrier.mqtt.password.trim()) {
    patch.barrier!.mqtt!.password = draft.barrier.mqtt.password.trim();
  }
  return patch;
};

/* -------------------------------------------------------------- controls */

function Toggle({
  label,
  hint,
  checked,
  onChange,
}: {
  label: string;
  hint?: string;
  checked: boolean;
  onChange: (value: boolean) => void;
}): JSX.Element {
  return (
    <label className="flex cursor-pointer items-start gap-2 rounded-xl border border-ink-200 p-3 text-xs transition hover:border-brand-300 dark:border-ink-700 dark:hover:border-brand-500/40">
      <input
        type="checkbox"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
        className="mt-0.5 h-4 w-4 shrink-0 rounded border-ink-300 text-brand-600 focus:ring-brand-500"
      />
      <span>
        <span className="block font-semibold text-ink-700 dark:text-ink-200">{label}</span>
        {hint ? <span className="mt-0.5 block text-[11px] leading-relaxed text-ink-400">{hint}</span> : null}
      </span>
    </label>
  );
}

function SecretField({
  label,
  stored,
  value,
  rotate,
  onChange,
  onRotate,
  keepHint,
  rotateHint,
  placeholder,
}: {
  label: string;
  stored: string | null;
  value: string;
  rotate: boolean;
  onChange: (value: string) => void;
  onRotate: (value: boolean) => void;
  keepHint: string;
  rotateHint: string;
  placeholder: string;
}): JSX.Element {
  const hasStored = Boolean(stored);
  return (
    <Field label={label} hint={hasStored && !rotate ? keepHint : rotateHint}>
      <div className="flex gap-2">
        <input
          type="password"
          autoComplete="new-password"
          value={rotate ? value : hasStored ? MASK : ""}
          disabled={hasStored && !rotate}
          onChange={(event) => onChange(event.target.value)}
          placeholder={placeholder}
          className="h-10 w-full rounded-xl border border-ink-200 bg-white px-3 font-mono text-sm text-ink-900 outline-none focus:border-brand-400 disabled:bg-ink-50 disabled:text-ink-400 dark:border-ink-700 dark:bg-ink-950 dark:text-ink-100 disabled:dark:bg-ink-900"
        />
        {hasStored ? (
          <Button
            size="sm"
            variant={rotate ? "outline" : "subtle"}
            onClick={() => {
              onRotate(!rotate);
              if (rotate) onChange("");
            }}
          >
            {rotate ? rotateHint : keepHint}
          </Button>
        ) : null}
      </div>
    </Field>
  );
}

/* ----------------------------------------------------------------- panel */

export function CompoundPolicyPanel({ compoundId }: { compoundId: string }): JSX.Element {
  const { t } = useI18n();
  const toast = useToast();
  const queryClient = useQueryClient();

  const settings = useQuery({
    queryKey: ["compound-settings", compoundId],
    queryFn: () => getCompoundSettings(compoundId),
    enabled: Boolean(compoundId),
  });

  const actuators = useQuery({
    queryKey: ["actuators", compoundId],
    queryFn: () => fetchActuatorStatus(compoundId),
    enabled: Boolean(compoundId),
    retry: false,
  });

  const effective = settings.data?.effective;
  const defaults = settings.data?.defaults;

  const [draft, setDraft] = useState<Draft | null>(null);
  const [rotate, setRotate] = useState({ webhook: false, mqtt: false });

  useEffect(() => {
    if (!effective) return;
    setDraft(toDraft(effective));
    setRotate({ webhook: false, mqtt: false });
  }, [effective]);

  const dirty = useMemo(() => {
    if (!draft || !effective) return false;
    const submitted = buildPatch(draft, effective, rotate);
    return JSON.stringify(submitted) !== JSON.stringify(buildPatch(toDraft(effective), effective, { webhook: false, mqtt: false }));
  }, [draft, effective, rotate]);

  const save = useMutation({
    mutationFn: async (): Promise<void> => {
      if (!draft || !effective) return;
      const updated = await updateCompoundSettings(compoundId, buildPatch(draft, effective, rotate));
      queryClient.setQueryData(["compound-settings", compoundId], updated);
      await queryClient.invalidateQueries({ queryKey: ["actuators", compoundId] });
      await queryClient.invalidateQueries({ queryKey: ["cv-real-mode"] });
    },
    onSuccess: () => toast.success(t("policy.toast.saved"), t("policy.toast.saved_hint")),
    onError: (error) => toast.error(t("policy.toast.save_error"), apiErrorMessage(error)),
  });

  const actuator = actuators.data?.compounds?.[0];

  if (!compoundId) {
    return <EmptyState icon="gate" title={t("policy.no_compound_title")} description={t("policy.no_compound_desc")} />;
  }

  if (settings.isLoading || !draft || !effective || !defaults) {
    return <Card><LoadingBlock label={t("policy.loading")} /></Card>;
  }

  if (settings.isError) {
    return (
      <Card>
        <EmptyState
          icon="alert"
          title={t("policy.error_title")}
          description={apiErrorMessage(settings.error)}
          action={
            <Button variant="outline" icon="refresh" onClick={() => void settings.refetch()}>
              {t("common.retry")}
            </Button>
          }
        />
      </Card>
    );
  }

  const setVision = (key: keyof Draft["vision"], value: string | boolean): void =>
    setDraft({ ...draft, vision: { ...draft.vision, [key]: value } });
  const setAccess = <K extends keyof Draft["access"]>(key: K, value: Draft["access"][K]): void =>
    setDraft({ ...draft, access: { ...draft.access, [key]: value } });
  const setBarrier = <K extends keyof Draft["barrier"]>(key: K, value: Draft["barrier"][K]): void =>
    setDraft({ ...draft, barrier: { ...draft.barrier, [key]: value } });

  const driver = draft.barrier.driver;

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader
          title={t("policy.title")}
          subtitle={t("policy.subtitle")}
          icon="gate"
          actions={
            <div className="flex flex-wrap items-center gap-2">
              {dirty ? <Badge tone="warning">{t("policy.unsaved")}</Badge> : <Badge tone="success" dot>{t("policy.saved_state")}</Badge>}
              <Button
                variant="outline"
                size="sm"
                icon="refresh"
                onClick={() => {
                  setDraft(toDraft(defaults));
                  setRotate({ webhook: false, mqtt: false });
                }}
              >
                {t("policy.action.defaults")}
              </Button>
              <Button
                variant="outline"
                size="sm"
                icon="refresh"
                onClick={() => void settings.refetch()}
                loading={settings.isFetching}
              >
                {t("policy.action.reload")}
              </Button>
              <Button size="sm" icon="check" onClick={() => save.mutate()} loading={save.isPending} disabled={!dirty}>
                {t("policy.action.save")}
              </Button>
            </div>
          }
        />
        <div className="grid gap-3 border-t border-ink-100 p-4 text-xs sm:grid-cols-2 dark:border-ink-800">
          <div className="flex items-center justify-between gap-2 rounded-xl bg-ink-50 p-3 dark:bg-ink-900">
            <span className="text-ink-500 dark:text-ink-400">{t("policy.driver.current")}</span>
            <Badge tone="info">{t(`policy.driver.${effective.barrier.driver}`)}</Badge>
          </div>
          <div className="flex items-center justify-between gap-2 rounded-xl bg-ink-50 p-3 dark:bg-ink-900">
            <span className="text-ink-500 dark:text-ink-400">{t("policy.driver.health")}</span>
            {actuator ? (
              <Badge tone={actuator.configured ? "success" : "warning"} dot>
                {actuator.configured ? t("policy.health.configured") : t("policy.health.not_configured")}
              </Badge>
            ) : (
              <span className="text-[11px] text-ink-400">{t("policy.health.unavailable")}</span>
            )}
          </div>
        </div>
      </Card>

      <Card>
        <CardHeader title={t("policy.section.barrier")} subtitle={t("policy.section.barrier_desc")} icon="gate" />
        <div className="space-y-4 p-4">
          <div className="grid gap-3 sm:grid-cols-2">
            <Select
              label={t("policy.driver.label")}
              value={driver}
              onChange={(event) => setBarrier("driver", event.target.value as BarrierDriver)}
              hint={t("policy.driver.hint")}
            >
              {DRIVERS.map((value) => (
                <option key={value} value={value}>{t(`policy.driver.${value}`)}</option>
              ))}
            </Select>
            <Input
              label={t("policy.simulator.latency")}
              type="number"
              min={0}
              max={5000}
              value={draft.barrier.simulator_latency_ms}
              onChange={(event) => setBarrier("simulator_latency_ms", event.target.value)}
              hint={t("policy.default_hint", { value: defaults.barrier.simulator_latency_ms })}
            />
          </div>

          {driver === "webhook" ? (
            <div className="space-y-3 rounded-xl border border-ink-200 p-3 dark:border-ink-700">
              <SectionTitle title={t("policy.webhook.title")} subtitle={t("policy.webhook.desc")} />
              <Input
                label={t("policy.webhook.url")}
                value={draft.barrier.webhook.url}
                onChange={(event) => setBarrier("webhook", { ...draft.barrier.webhook, url: event.target.value })}
                placeholder="https://controller.local/open"
                className="font-mono"
              />
              <SecretField
                label={t("policy.webhook.secret")}
                stored={effective.barrier.webhook.secret}
                value={draft.barrier.webhook.secret}
                rotate={rotate.webhook}
                onChange={(value) => setBarrier("webhook", { ...draft.barrier.webhook, secret: value })}
                onRotate={(value) => setRotate({ ...rotate, webhook: value })}
                keepHint={t("policy.secret.keep")}
                rotateHint={t("policy.secret.rotate")}
                placeholder={t("policy.webhook.secret_placeholder")}
              />
              <div className="grid gap-3 sm:grid-cols-2">
                <Input
                  label={t("policy.webhook.timeout")}
                  type="number"
                  step="0.5"
                  min={0.5}
                  max={30}
                  value={draft.barrier.webhook.timeout_seconds}
                  onChange={(event) => setBarrier("webhook", { ...draft.barrier.webhook, timeout_seconds: event.target.value })}
                  hint={t("policy.default_hint", { value: defaults.barrier.webhook.timeout_seconds })}
                />
                <Input
                  label={t("policy.webhook.retries")}
                  type="number"
                  min={0}
                  max={5}
                  value={draft.barrier.webhook.retries}
                  onChange={(event) => setBarrier("webhook", { ...draft.barrier.webhook, retries: event.target.value })}
                  hint={t("policy.default_hint", { value: defaults.barrier.webhook.retries })}
                />
              </div>
              <Toggle
                label={t("policy.webhook.verify_tls")}
                hint={t("policy.webhook.verify_tls_hint")}
                checked={draft.barrier.webhook.verify_tls}
                onChange={(value) => setBarrier("webhook", { ...draft.barrier.webhook, verify_tls: value })}
              />
            </div>
          ) : null}

          {driver === "mqtt" ? (
            <div className="space-y-3 rounded-xl border border-ink-200 p-3 dark:border-ink-700">
              <SectionTitle title={t("policy.mqtt.title")} subtitle={t("policy.mqtt.desc")} />
              <div className="grid gap-3 sm:grid-cols-2">
                <Input
                  label={t("policy.mqtt.host")}
                  value={draft.barrier.mqtt.host}
                  onChange={(event) => setBarrier("mqtt", { ...draft.barrier.mqtt, host: event.target.value })}
                  placeholder="broker.local"
                  className="font-mono"
                />
                <Input
                  label={t("policy.mqtt.port")}
                  type="number"
                  min={1}
                  max={65535}
                  value={draft.barrier.mqtt.port}
                  onChange={(event) => setBarrier("mqtt", { ...draft.barrier.mqtt, port: event.target.value })}
                />
                <Input
                  label={t("policy.mqtt.topic")}
                  value={draft.barrier.mqtt.topic}
                  onChange={(event) => setBarrier("mqtt", { ...draft.barrier.mqtt, topic: event.target.value })}
                  placeholder="gatevision/{gate}/command"
                  className="font-mono sm:col-span-2"
                />
                <Select
                  label={t("policy.mqtt.qos")}
                  value={draft.barrier.mqtt.qos}
                  onChange={(event) => setBarrier("mqtt", { ...draft.barrier.mqtt, qos: event.target.value })}
                >
                  <option value="0">0</option>
                  <option value="1">1</option>
                  <option value="2">2</option>
                </Select>
                <Input
                  label={t("policy.mqtt.username")}
                  value={draft.barrier.mqtt.username}
                  onChange={(event) => setBarrier("mqtt", { ...draft.barrier.mqtt, username: event.target.value })}
                  placeholder={t("common.optional")}
                />
              </div>
              <SecretField
                label={t("policy.mqtt.password")}
                stored={effective.barrier.mqtt.password}
                value={draft.barrier.mqtt.password}
                rotate={rotate.mqtt}
                onChange={(value) => setBarrier("mqtt", { ...draft.barrier.mqtt, password: value })}
                onRotate={(value) => setRotate({ ...rotate, mqtt: value })}
                keepHint={t("policy.secret.keep")}
                rotateHint={t("policy.secret.rotate")}
                placeholder={t("policy.mqtt.password_placeholder")}
              />
              <div className="grid gap-3 sm:grid-cols-2">
                <Toggle
                  label={t("policy.mqtt.tls")}
                  checked={draft.barrier.mqtt.tls}
                  onChange={(value) => setBarrier("mqtt", { ...draft.barrier.mqtt, tls: value })}
                />
                <Toggle
                  label={t("policy.mqtt.simulate")}
                  hint={t("policy.mqtt.simulate_hint")}
                  checked={draft.barrier.mqtt.simulate}
                  onChange={(value) => setBarrier("mqtt", { ...draft.barrier.mqtt, simulate: value })}
                />
              </div>
            </div>
          ) : null}

          {driver === "gpio" ? (
            <div className="space-y-3 rounded-xl border border-ink-200 p-3 dark:border-ink-700">
              <SectionTitle title={t("policy.gpio.title")} subtitle={t("policy.gpio.desc")} />
              <div className="grid gap-3 sm:grid-cols-3">
                <Input
                  label={t("policy.gpio.open_pin")}
                  type="number"
                  min={1}
                  max={40}
                  value={draft.barrier.gpio.open_pin}
                  onChange={(event) => setBarrier("gpio", { ...draft.barrier.gpio, open_pin: event.target.value })}
                />
                <Input
                  label={t("policy.gpio.close_pin")}
                  type="number"
                  min={1}
                  max={40}
                  value={draft.barrier.gpio.close_pin}
                  onChange={(event) => setBarrier("gpio", { ...draft.barrier.gpio, close_pin: event.target.value })}
                />
                <Input
                  label={t("policy.gpio.hold_pin")}
                  type="number"
                  min={1}
                  max={40}
                  value={draft.barrier.gpio.hold_pin}
                  onChange={(event) => setBarrier("gpio", { ...draft.barrier.gpio, hold_pin: event.target.value })}
                  placeholder={t("common.optional")}
                />
                <Input
                  label={t("policy.gpio.pulse")}
                  type="number"
                  step="0.1"
                  min={0.05}
                  max={10}
                  value={draft.barrier.gpio.pulse_seconds}
                  onChange={(event) => setBarrier("gpio", { ...draft.barrier.gpio, pulse_seconds: event.target.value })}
                />
                <Select
                  label={t("policy.gpio.backend")}
                  value={draft.barrier.gpio.backend}
                  onChange={(event) => setBarrier("gpio", { ...draft.barrier.gpio, backend: event.target.value })}
                >
                  <option value="gpiozero">gpiozero</option>
                  <option value="rpi_gpio">rpi_gpio</option>
                </Select>
                <div className="grid gap-2">
                  <Toggle
                    label={t("policy.gpio.active_high")}
                    checked={draft.barrier.gpio.active_high}
                    onChange={(value) => setBarrier("gpio", { ...draft.barrier.gpio, active_high: value })}
                  />
                </div>
              </div>
              <Toggle
                label={t("policy.gpio.simulate")}
                hint={t("policy.gpio.simulate_hint")}
                checked={draft.barrier.gpio.simulate}
                onChange={(value) => setBarrier("gpio", { ...draft.barrier.gpio, simulate: value })}
              />
            </div>
          ) : null}

          {driver === "simulator" ? (
            <div className="grid gap-3 rounded-xl border border-ink-200 p-3 sm:grid-cols-2 dark:border-ink-700">
              <Input
                label={t("policy.simulator.failure_rate")}
                type="number"
                step="0.05"
                min={0}
                max={1}
                value={draft.barrier.simulator_failure_rate}
                onChange={(event) => setBarrier("simulator_failure_rate", event.target.value)}
                hint={t("policy.default_hint", { value: defaults.barrier.simulator_failure_rate })}
              />
              <p className="self-end pb-2 text-[11px] leading-relaxed text-ink-400">{t("policy.simulator.desc")}</p>
            </div>
          ) : null}
        </div>
      </Card>

      <Card>
        <CardHeader title={t("policy.section.vision")} subtitle={t("policy.section.vision_desc")} icon="camera" />
        <div className="grid gap-3 p-4 sm:grid-cols-2 lg:grid-cols-3">
          <Input
            label={t("policy.vision.plate_confidence")}
            type="number"
            step="0.01"
            min={0.05}
            max={0.95}
            value={draft.vision.plate_confidence_threshold}
            onChange={(event) => setVision("plate_confidence_threshold", event.target.value)}
            hint={t("policy.default_hint", { value: defaults.vision.plate_confidence_threshold })}
          />
          <Input
            label={t("policy.vision.ocr_confidence")}
            type="number"
            step="0.01"
            min={0.05}
            max={0.98}
            value={draft.vision.ocr_min_confidence}
            onChange={(event) => setVision("ocr_min_confidence", event.target.value)}
            hint={t("policy.default_hint", { value: defaults.vision.ocr_min_confidence })}
          />
          <Input
            label={t("policy.vision.face_similarity")}
            type="number"
            step="0.01"
            min={0.2}
            max={0.85}
            value={draft.vision.face_similarity_threshold}
            onChange={(event) => setVision("face_similarity_threshold", event.target.value)}
            hint={t("policy.default_hint", { value: defaults.vision.face_similarity_threshold })}
          />
          <Input
            label={t("policy.vision.face_min_quality")}
            type="number"
            min={0}
            max={100}
            value={draft.vision.face_min_quality}
            onChange={(event) => setVision("face_min_quality", event.target.value)}
            hint={t("policy.default_hint", { value: defaults.vision.face_min_quality })}
          />
          <Input
            label={t("policy.vision.face_min_resolution")}
            type="number"
            min={80}
            max={2000}
            value={draft.vision.face_min_resolution}
            onChange={(event) => setVision("face_min_resolution", event.target.value)}
            hint={t("policy.default_hint", { value: defaults.vision.face_min_resolution })}
          />
          <Input
            label={t("policy.vision.face_min_blur")}
            type="number"
            step="0.5"
            min={0}
            max={500}
            value={draft.vision.face_min_blur}
            onChange={(event) => setVision("face_min_blur", event.target.value)}
            hint={t("policy.default_hint", { value: defaults.vision.face_min_blur })}
          />
          <Input
            label={t("policy.vision.max_embeddings")}
            type="number"
            min={1}
            max={10}
            value={draft.vision.max_embeddings_per_resident}
            onChange={(event) => setVision("max_embeddings_per_resident", event.target.value)}
            hint={t("policy.default_hint", { value: defaults.vision.max_embeddings_per_resident })}
          />
          <Input
            label={t("policy.vision.duplicate_similarity")}
            type="number"
            step="0.005"
            min={0.5}
            max={0.995}
            value={draft.vision.duplicate_similarity_threshold}
            onChange={(event) => setVision("duplicate_similarity_threshold", event.target.value)}
            hint={t("policy.default_hint", { value: defaults.vision.duplicate_similarity_threshold })}
          />
          <Toggle
            label={t("policy.vision.reject_duplicates")}
            hint={t("policy.vision.reject_duplicates_hint")}
            checked={draft.vision.reject_duplicate_enrollment}
            onChange={(value) => setVision("reject_duplicate_enrollment", value)}
          />
        </div>
      </Card>

      <Card>
        <CardHeader title={t("policy.section.access")} subtitle={t("policy.section.access_desc")} icon="shield" />
        <div className="space-y-3 p-4">
          <div className="grid gap-3 sm:grid-cols-2">
            <Select
              label={t("policy.access.unknown_vehicle")}
              value={draft.access.unknown_vehicle_decision}
              onChange={(event) =>
                setAccess("unknown_vehicle_decision", event.target.value as Draft["access"]["unknown_vehicle_decision"])
              }
              hint={t("policy.access.unknown_vehicle_hint")}
            >
              <option value="unknown">{t("decision.unknown")}</option>
              <option value="review">{t("decision.review")}</option>
              <option value="deny">{t("decision.deny")}</option>
            </Select>
            <Input
              label={t("policy.access.exit_grace")}
              type="number"
              min={0}
              max={720}
              value={draft.access.exit_grace_minutes}
              onChange={(event) => setAccess("exit_grace_minutes", event.target.value)}
              hint={t("policy.default_hint", { value: defaults.access.exit_grace_minutes })}
            />
          </div>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            <Toggle
              label={t("policy.access.auto_open")}
              hint={t("policy.access.auto_open_hint")}
              checked={draft.access.auto_open_barrier}
              onChange={(value) => setAccess("auto_open_barrier", value)}
            />
            <Toggle
              label={t("policy.access.face_only")}
              hint={t("policy.access.face_only_hint")}
              checked={draft.access.allow_face_only_entry}
              onChange={(value) => setAccess("allow_face_only_entry", value)}
            />
            <Toggle
              label={t("policy.access.require_face")}
              hint={t("policy.access.require_face_hint")}
              checked={draft.access.require_face_for_vehicle}
              onChange={(value) => setAccess("require_face_for_vehicle", value)}
            />
            <Toggle
              label={t("policy.access.blacklist_exit")}
              hint={t("policy.access.blacklist_exit_hint")}
              checked={draft.access.allow_blacklist_exit}
              onChange={(value) => setAccess("allow_blacklist_exit", value)}
            />
            <Toggle
              label={t("policy.access.visitor_late_exit")}
              hint={t("policy.access.visitor_late_exit_hint")}
              checked={draft.access.allow_visitor_exit_after_expiry}
              onChange={(value) => setAccess("allow_visitor_exit_after_expiry", value)}
            />
          </div>
        </div>
      </Card>

      <Card>
        <CardHeader
          title={t("policy.section.health")}
          subtitle={t("policy.section.health_desc")}
          icon="live"
          actions={
            <Button variant="outline" size="sm" icon="refresh" onClick={() => void actuators.refetch()} loading={actuators.isFetching}>
              {t("common.refresh")}
            </Button>
          }
        />
        <div className="space-y-3 p-4 text-xs">
          {actuator ? (
            <>
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone="info">{t(`policy.driver.${actuator.driver}`, {})}</Badge>
                <Badge tone={actuator.configured ? "success" : "warning"} dot>
                  {actuator.configured ? t("policy.health.configured") : t("policy.health.not_configured")}
                </Badge>
                {actuator.name ? <span className="font-mono text-[11px] text-ink-400">{actuator.name}</span> : null}
              </div>
              {actuator.warnings.length > 0 ? (
                <ul className="space-y-1 text-[11px] text-amber-700 dark:text-amber-300">
                  {actuator.warnings.map((warning) => (
                    <li key={warning} className="flex gap-2">
                      <Icon name="alert" className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                      <span>{warning}</span>
                    </li>
                  ))}
                </ul>
              ) : null}
              {actuator.recent_commands.length > 0 ? (
                <TableLike commands={actuator.recent_commands} />
              ) : (
                <p className="text-[11px] text-ink-400">{t("policy.health.no_commands")}</p>
              )}
            </>
          ) : (
            <p className="text-[11px] text-ink-400">{t("policy.health.unavailable")}</p>
          )}
        </div>
      </Card>
    </div>
  );
}

function TableLike({
  commands,
}: {
  commands: { id: string; occurred_at: string; gate_code: string; action: string; accepted: boolean; latency_ms: number; detail: string }[];
}): JSX.Element {
  const { t } = useI18n();
  return (
    <div className="overflow-hidden rounded-xl border border-ink-200 dark:border-ink-700">
      <table className="w-full text-left text-[11px]">
        <thead className="bg-ink-50 text-ink-500 dark:bg-ink-900 dark:text-ink-400">
          <tr>
            <th className="px-3 py-2 font-semibold">{t("common.when")}</th>
            <th className="px-3 py-2 font-semibold">{t("common.gate")}</th>
            <th className="px-3 py-2 font-semibold">{t("common.method")}</th>
            <th className="px-3 py-2 font-semibold">{t("common.status")}</th>
            <th className="px-3 py-2 font-semibold">{t("policy.health.latency")}</th>
          </tr>
        </thead>
        <tbody>
          {commands.slice(0, 5).map((command) => (
            <tr key={command.id} className="border-t border-ink-100 dark:border-ink-800">
              <td className="px-3 py-2 text-ink-500 dark:text-ink-400">{formatDateTime(command.occurred_at)}</td>
              <td className="px-3 py-2 font-mono">{command.gate_code}</td>
              <td className="px-3 py-2">{command.action}</td>
              <td className="px-3 py-2">
                <Badge tone={command.accepted ? "success" : "danger"} dot>
                  {command.accepted ? t("policy.health.accepted") : t("policy.health.rejected")}
                </Badge>
              </td>
              <td className="px-3 py-2 font-mono">{command.latency_ms} ms</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
