import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { CompoundPolicyPanel } from "@/components/CompoundPolicyPanel";
import { Icon } from "@/components/Icon";
import { PageHeader } from "@/components/PageHeader";
import {
  Badge,
  Button,
  Card,
  CardHeader,
  ConfirmDialog,
  EmptyState,
  Input,
  LoadingBlock,
  Modal,
  Select,
  TableShell,
  Tabs,
  Td,
  Textarea,
  Th,
} from "@/components/ui";
import { useAuth } from "@/hooks/useAuth";
import { useI18n } from "@/i18n";
import { useToast } from "@/hooks/useToast";
import {
  createCamera,
  createCompound,
  createGate,
  createUser,
  deactivateUser,
  deleteCamera,
  deleteGate,
  gateCommand,
  listCameras,
  listCompounds,
  listGates,
  listUsers,
  resetUserPassword,
  toggleCamera,
  updateCamera,
  updateCompound,
  updateGate,
  updateUser,
  type CameraPayload,
  type GatePayload,
  type UserPayload,
} from "@/services/admin";
import { apiErrorMessage } from "@/services/api";
import { fetchRealModeStatus, testCameraStream } from "@/services/cv";
import type {
  Camera,
  CameraProbeResult,
  CameraSourceType,
  Gate,
  GateDirection,
  GateStatus,
  User,
  UserRole,
} from "@/types/models";
import { GATE_STATUS_META } from "@/utils/constants";
import { formatDateTime, initials } from "@/utils/format";

type TabKey = "gates" | "cameras" | "policy" | "users" | "account";

const EMPTY_GATE: GatePayload = {
  compound_id: "",
  name: "",
  code: "",
  direction: "entry",
  status: "online",
  location: "",
  notes: "",
};

const EMPTY_CAMERA: CameraPayload = {
  gate_id: "",
  name: "",
  source_type: "rtsp",
  source_url: "",
  fps_limit: 5,
  position: "front",
  notes: "",
};

const EMPTY_USER = {
  email: "",
  full_name: "",
  password: "",
  role: "security_officer" as UserRole,
  phone: "",
};

export function SettingsPage(): JSX.Element {
  const { t } = useI18n();
  const { user, hasRole, changePassword } = useAuth();
  const isAdmin = hasRole("admin");
  const isManager = hasRole("admin", "security_officer");
  const toast = useToast();
  const queryClient = useQueryClient();

  const [tab, setTab] = useState<TabKey>(isManager ? "gates" : "account");
  const [gateOpen, setGateOpen] = useState(false);
  const [gateForm, setGateForm] = useState<GatePayload>(EMPTY_GATE);
  const [editingGate, setEditingGate] = useState<Gate | null>(null);
  const [gateToDelete, setGateToDelete] = useState<Gate | null>(null);

  const [cameraOpen, setCameraOpen] = useState(false);
  const [cameraForm, setCameraForm] = useState<CameraPayload>(EMPTY_CAMERA);
  const [editingCamera, setEditingCamera] = useState<Camera | null>(null);
  const [cameraToDelete, setCameraToDelete] = useState<Camera | null>(null);
  const [probe, setProbe] = useState<{ camera: Camera; result: CameraProbeResult | null } | null>(
    null,
  );
  const realMode = useQuery({
    queryKey: ["cv-real-mode"],
    queryFn: fetchRealModeStatus,
    retry: false,
    refetchInterval: 60_000,
  });

  const [userOpen, setUserOpen] = useState(false);
  const [userForm, setUserForm] = useState(EMPTY_USER);
  const [userToDeactivate, setUserToDeactivate] = useState<User | null>(null);
  const [passwordTarget, setPasswordTarget] = useState<User | null>(null);
  const [newPassword, setNewPassword] = useState("");

  const [compoundForm, setCompoundForm] = useState({
    name: "",
    code: "",
    city: "",
    contact_phone: "",
    contact_email: "",
  });
  const [accountForm, setAccountForm] = useState({ current: "", next: "", confirm: "" });

  const compounds = useQuery({ queryKey: ["compounds"], queryFn: listCompounds });
  const compound = compounds.data?.items[0];
  const gates = useQuery({ queryKey: ["gates"], queryFn: () => listGates() });
  const cameras = useQuery({ queryKey: ["cameras"], queryFn: listCameras, enabled: isManager });
  const users = useQuery({ queryKey: ["users"], queryFn: () => listUsers(), enabled: isAdmin });

  const gateOptions = gates.data?.items ?? [];

  useEffect(() => {
    if (!compound) return;
    setCompoundForm({
      name: compound.name,
      code: compound.code,
      city: compound.city ?? "",
      contact_phone: compound.contact_phone ?? "",
      contact_email: compound.contact_email ?? "",
    });
  }, [compound]);

  const invalidate = async (): Promise<void> => {
    await queryClient.invalidateQueries({ queryKey: ["gates"] });
    await queryClient.invalidateQueries({ queryKey: ["cameras"] });
    await queryClient.invalidateQueries({ queryKey: ["users"] });
    await queryClient.invalidateQueries({ queryKey: ["compounds"] });
    await queryClient.invalidateQueries({ queryKey: ["dashboard"] });
  };

  const gateMutation = useMutation({
    mutationFn: async (): Promise<void> => {
      if (!compound) throw new Error(t("settings.error.no_compound"));
      const payload: GatePayload = { ...gateForm, compound_id: compound.id };
      if (editingGate) {
        await updateGate(editingGate.id, {
          name: payload.name,
          direction: payload.direction,
          status: payload.status,
          location: payload.location,
          notes: payload.notes,
        });
      } else {
        await createGate(payload);
      }
    },
    onSuccess: async () => {
      toast.success(editingGate ? t("settings.toast.gate_saved") : t("settings.toast.gate_created"));
      setGateOpen(false);
      setEditingGate(null);
      setGateForm(EMPTY_GATE);
      await invalidate();
    },
    onError: (error) => toast.error(t("settings.toast.gate_error"), apiErrorMessage(error)),
  });

  const cameraMutation = useMutation({
    mutationFn: async (): Promise<void> => {
      if (!cameraForm.gate_id) throw new Error(t("settings.error.select_gate"));
      if (editingCamera) {
        const payload = {
          name: cameraForm.name,
          source_type: cameraForm.source_type,
          fps_limit: cameraForm.fps_limit,
          position: cameraForm.position,
          notes: cameraForm.notes,
        };
        // The API masks credentials; an untouched field means "keep the stored
        // URL" and must not overwrite it with asterisks.
        await updateCamera(
          editingCamera.id,
          cameraForm.source_url.trim() && cameraForm.source_url !== editingCamera.source_url
            ? { ...payload, source_url: cameraForm.source_url.trim() }
            : payload,
        );
      } else {
        await createCamera(cameraForm);
      }
    },
    onSuccess: async () => {
      toast.success(editingCamera ? t("settings.toast.camera_saved") : t("settings.toast.camera_created"));
      setCameraOpen(false);
      setEditingCamera(null);
      setCameraForm(EMPTY_CAMERA);
      await invalidate();
    },
    onError: (error) => toast.error(t("settings.toast.camera_error"), apiErrorMessage(error)),
  });

  const userMutation = useMutation({
    mutationFn: async (): Promise<void> => {
      const payload: UserPayload = {
        email: userForm.email.trim().toLowerCase(),
        full_name: userForm.full_name.trim(),
        password: userForm.password,
        role: userForm.role,
        phone: userForm.phone.trim() || null,
        compound_id: userForm.role === "admin" ? null : compound?.id ?? null,
      };
      await createUser(payload);
    },
    onSuccess: async () => {
      toast.success(t("settings.toast.user_created"));
      setUserOpen(false);
      setUserForm(EMPTY_USER);
      await invalidate();
    },
    onError: (error) => toast.error(t("settings.toast.user_error"), apiErrorMessage(error)),
  });

  const resetPasswordMutation = useMutation({
    mutationFn: ({ id, password }: { id: string; password: string }) => resetUserPassword(id, password),
    onSuccess: () => {
      toast.success(t("settings.toast.password_reset"));
      setPasswordTarget(null);
      setNewPassword("");
    },
    onError: (error) => toast.error(t("settings.toast.password_error"), apiErrorMessage(error)),
  });

  const deactivateMutation = useMutation({
    mutationFn: (target: User) => deactivateUser(target.id),
    onSuccess: async () => {
      toast.success(t("settings.toast.user_deactivated"));
      setUserToDeactivate(null);
      await invalidate();
    },
    onError: (error) => toast.error(t("settings.toast.deactivate_error"), apiErrorMessage(error)),
  });

  const toggleCameraMutation = useMutation({
    mutationFn: ({ camera, active }: { camera: Camera; active: boolean }) => toggleCamera(camera.id, active),
    onSuccess: async (camera) => {
      toast.success(t("settings.toast.camera_status", { status: t(`status.${camera.status}`) }));
      await invalidate();
    },
    onError: (error) => toast.error(t("settings.toast.camera_toggle_error"), apiErrorMessage(error)),
  });

  const probeMutation = useMutation({
    mutationFn: (camera: Camera) => testCameraStream(camera.id),
    onSuccess: async (result, camera) => {
      setProbe({ camera, result });
      if (result.ok) {
        toast.success(
          t("settings.toast.probe_ok"),
          t("settings.toast.probe_ok_detail", {
            width: result.width ?? "?",
            height: result.height ?? "?",
            latency: result.latency_ms,
          }),
        );
      } else {
        toast.error(t("settings.toast.probe_failed"), result.error ?? undefined);
      }
      await invalidate();
    },
    onError: (error, camera) => {
      setProbe({ camera, result: null });
      toast.error(t("settings.toast.probe_failed"), apiErrorMessage(error));
    },
  });

  const deleteCameraMutation = useMutation({
    mutationFn: (camera: Camera) => deleteCamera(camera.id),
    onSuccess: async () => {
      toast.success(t("settings.toast.camera_deleted"));
      setCameraToDelete(null);
      await invalidate();
    },
    onError: (error) => toast.error(t("settings.toast.camera_delete_error"), apiErrorMessage(error)),
  });

  const deleteGateMutation = useMutation({
    mutationFn: (gate: Gate) => deleteGate(gate.id),
    onSuccess: async () => {
      toast.success(t("settings.toast.gate_deleted"));
      setGateToDelete(null);
      await invalidate();
    },
    onError: (error) => toast.error(t("settings.toast.gate_delete_error"), apiErrorMessage(error)),
  });

  const commandMutation = useMutation({
    mutationFn: (gate: Gate) => gateCommand(gate.id, "open", t("settings.command_reason")),
    onSuccess: (result) => toast.success(t("settings.toast.command_accepted"), result.detail),
    onError: (error) => toast.error(t("settings.toast.command_failed"), apiErrorMessage(error)),
  });

  const createCompoundMutation = useMutation({
    mutationFn: () =>
      createCompound({
        name: compoundForm.name.trim(),
        code: compoundForm.code.trim().toUpperCase() || "COMPOUND",
        city: compoundForm.city || null,
        contact_phone: compoundForm.contact_phone || null,
        contact_email: compoundForm.contact_email || null,
      }),
    onSuccess: async () => {
      toast.success(t("settings.toast.compound_created"));
      setCompoundForm({ name: "", code: "", city: "", contact_phone: "", contact_email: "" });
      await invalidate();
    },
    onError: (error) => toast.error(t("settings.toast.compound_error"), apiErrorMessage(error)),
  });

  const compoundMutation = useMutation({
    mutationFn: async (): Promise<void> => {
      if (!compound) throw new Error(t("settings.error.no_compound"));
      await updateCompound(compound.id, {
        name: compoundForm.name || compound.name,
        city: compoundForm.city || compound.city,
        contact_phone: compoundForm.contact_phone || compound.contact_phone,
        contact_email: compoundForm.contact_email || compound.contact_email,
      });
    },
    onSuccess: async () => {
      toast.success(t("settings.toast.compound_updated"));
      await invalidate();
    },
    onError: (error) => toast.error(t("settings.toast.compound_error"), apiErrorMessage(error)),
  });

  const accountMutation = useMutation({
    mutationFn: async (): Promise<void> => {
      if (accountForm.next !== accountForm.confirm) throw new Error(t("settings.account.password_mismatch"));
      await changePassword(accountForm.current, accountForm.next);
    },
    onSuccess: () => {
      toast.success(t("settings.toast.password_changed"));
      setAccountForm({ current: "", next: "", confirm: "" });
    },
    onError: (error) => toast.error(t("settings.toast.password_change_error"), apiErrorMessage(error)),
  });

  const openCreateGate = (): void => {
    setEditingGate(null);
    setGateForm({ ...EMPTY_GATE, compound_id: compound?.id ?? "" });
    setGateOpen(true);
  };

  const openEditGate = (gate: Gate): void => {
    setEditingGate(gate);
    setGateForm({
      compound_id: gate.compound_id,
      name: gate.name,
      code: gate.code,
      direction: gate.direction,
      status: gate.status,
      location: gate.location ?? "",
      notes: gate.notes ?? "",
    });
    setGateOpen(true);
  };

  const openCreateCamera = (gateId?: string): void => {
    setEditingCamera(null);
    setCameraForm({ ...EMPTY_CAMERA, gate_id: gateId ?? gateOptions[0]?.id ?? "" });
    setCameraOpen(true);
  };

  const openEditCamera = (camera: Camera): void => {
    setEditingCamera(camera);
    setCameraForm({
      gate_id: camera.gate_id,
      name: camera.name,
      source_type: camera.source_type,
      // Leave blank so a masked URL is never written back; the placeholder
      // shows the currently configured (masked) address.
      source_url: "",
      fps_limit: camera.fps_limit,
      position: camera.position,
      notes: camera.notes ?? "",
    });
    setCameraOpen(true);
  };

  const tabs: { key: TabKey; label: string }[] = [
    ...(isManager ? [{ key: "gates" as TabKey, label: t("settings.tab.gates") }] : []),
    ...(isManager ? [{ key: "cameras" as TabKey, label: t("settings.tab.cameras") }] : []),
    ...(isAdmin ? [{ key: "policy" as TabKey, label: t("settings.tab.policy") }] : []),
    ...(isAdmin ? [{ key: "users" as TabKey, label: t("settings.tab.users") }] : []),
    { key: "account", label: t("settings.tab.account") },
  ];

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow={t("settings.eyebrow")}
        title={t("settings.title")}
        subtitle={t("settings.subtitle")}
        actions={
          tab === "gates" ? (
            <Button icon="plus" onClick={openCreateGate}>{t("settings.add_gate")}</Button>
          ) : tab === "cameras" ? (
            <Button icon="plus" onClick={() => openCreateCamera()}>{t("settings.add_camera")}</Button>
          ) : tab === "users" ? (
            <Button icon="plus" onClick={() => setUserOpen(true)}>{t("settings.create_user")}</Button>
          ) : null
        }
      />

      <Tabs tabs={tabs} value={tab} onChange={setTab} />

      {tab === "gates" ? (
        <Card>
          <CardHeader title={t("settings.gates.title")} subtitle={t("settings.gates.subtitle")} icon="gate" />
          {gates.isLoading ? (
            <LoadingBlock />
          ) : gateOptions.length === 0 ? (
            <EmptyState icon="gate" title={t("settings.gates.empty_title")} description={t("settings.gates.empty_description")} action={<Button icon="plus" onClick={openCreateGate}>{t("settings.add_gate")}</Button>} />
          ) : (
            <TableShell>
              <thead>
                <tr>
                  <Th>{t("settings.table.gate")}</Th>
                  <Th>{t("common.direction")}</Th>
                  <Th>{t("common.status")}</Th>
                  <Th>{t("settings.table.cameras")}</Th>
                  <Th>{t("settings.table.location")}</Th>
                  <Th align="right">{t("common.actions")}</Th>
                </tr>
              </thead>
              <tbody>
                {gateOptions.map((gate) => (
                  <tr key={gate.id} className="transition hover:bg-ink-50/70 dark:hover:bg-ink-800/30">
                    <Td>
                      <p className="text-sm font-semibold text-ink-900 dark:text-ink-100">{gate.name}</p>
                      <p className="font-mono text-[10px] text-ink-400">{gate.code}</p>
                    </Td>
                    <Td className="text-xs capitalize">{t(`direction.${gate.direction}`)}</Td>
                    <Td><Badge tone={GATE_STATUS_META[gate.status].tone} dot>{t(`status.${gate.status}`)}</Badge></Td>
                    <Td className="text-xs">{gate.cameras.length}</Td>
                    <Td className="text-xs">{gate.location ?? "—"}</Td>
                    <Td align="right">
                      <div className="flex justify-end gap-1">
                        <Button size="sm" variant="subtle" icon="play" onClick={() => commandMutation.mutate(gate)}>{t("settings.action.open")}</Button>
                        <Button size="icon" variant="ghost" onClick={() => openCreateCamera(gate.id)} aria-label={t("settings.action.add_camera")}><Icon name="camera" className="h-4 w-4" /></Button>
                        <Button size="icon" variant="ghost" onClick={() => openEditGate(gate)} aria-label={t("settings.action.edit_gate")}><Icon name="edit" className="h-4 w-4" /></Button>
                        {isAdmin ? (
                          <Button size="icon" variant="ghost" onClick={() => setGateToDelete(gate)} aria-label={t("settings.action.delete_gate")}><Icon name="trash" className="h-4 w-4 text-rose-500" /></Button>
                        ) : null}
                      </div>
                    </Td>
                  </tr>
                ))}
              </tbody>
            </TableShell>
          )}
        </Card>
      ) : null}

      {tab === "cameras" ? (
        <>
        <Card>
          <CardHeader
            title={t("settings.vision.title")}
            subtitle={t("settings.vision.subtitle")}
            icon="sparkles"
            actions={
              realMode.data ? (
                <Badge tone={realMode.data.real_detections_only ? "success" : "warning"} dot>
                  {realMode.data.real_detections_only
                    ? t("settings.vision.real_badge")
                    : t("settings.vision.mock_badge")}
                </Badge>
              ) : null
            }
          />
          <div className="grid gap-3 p-4 sm:grid-cols-2">
            <div className="rounded-xl border border-ink-200 p-3 text-xs dark:border-ink-800">
              <p className="text-[10px] font-semibold uppercase text-ink-400">{t("settings.vision.mode")}</p>
              <p className="mt-0.5 font-mono text-sm text-ink-900 dark:text-ink-100">
                {realMode.data?.mode ?? "—"}
              </p>
              <p className="mt-1 text-[11px] text-ink-500 dark:text-ink-400">
                {t("settings.vision.cameras", {
                  online: realMode.data?.cameras_online ?? 0,
                  total: realMode.data?.cameras_total ?? 0,
                })}
              </p>
            </div>
            <div className="rounded-xl border border-ink-200 p-3 text-xs dark:border-ink-800">
              <p className="text-[10px] font-semibold uppercase text-ink-400">{t("settings.vision.barrier")}</p>
              <p className="mt-0.5 font-mono text-sm text-ink-900 dark:text-ink-100">
                {realMode.data?.barrier_driver ?? "—"}
              </p>
              <p className="mt-1 text-[11px] text-ink-500 dark:text-ink-400">
                {realMode.data?.engine_ready
                  ? t("settings.vision.engine_ready")
                  : t("settings.vision.engine_not_ready")}
              </p>
            </div>
            <div className="rounded-xl border border-ink-200 p-3 text-xs sm:col-span-2 dark:border-ink-800">
              <p className="text-[10px] font-semibold uppercase text-ink-400">{t("settings.vision.models")}</p>
              <dl className="mt-1 grid gap-1 text-[11px] sm:grid-cols-2">
                {Object.entries(realMode.data?.models ?? {}).map(([key, value]) => (
                  <div key={key} className="flex min-w-0 gap-2">
                    <dt className="shrink-0 font-semibold text-ink-500 dark:text-ink-400">{key}</dt>
                    <dd className="truncate font-mono text-ink-700 dark:text-ink-200" title={String(value)}>
                      {String(value)}
                    </dd>
                  </div>
                ))}
              </dl>
              {realMode.data ? (
                <p
                  className={`mt-2 flex items-center gap-1.5 text-[11px] ${
                    realMode.data.plate_model_present
                      ? "text-emerald-600 dark:text-emerald-400"
                      : "text-amber-700 dark:text-amber-300"
                  }`}
                >
                  <Icon
                    name={realMode.data.plate_model_present ? "check" : "alert"}
                    className="h-3.5 w-3.5 shrink-0"
                  />
                  <span>
                    {realMode.data.plate_model_present
                      ? t("settings.vision.model_present")
                      : t("settings.vision.model_missing")}
                  </span>
                </p>
              ) : null}
            </div>
            {(realMode.data?.warnings ?? []).length > 0 ? (
              <ul className="space-y-1 text-[11px] text-amber-700 sm:col-span-2 dark:text-amber-300">
                {(realMode.data?.warnings ?? []).map((warning) => (
                  <li key={warning} className="flex gap-2">
                    <Icon name="alert" className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                    <span>{warning}</span>
                  </li>
                ))}
              </ul>
            ) : null}
          </div>
        </Card>

        <Card>
          <CardHeader title={t("settings.cameras.title")} subtitle={t("settings.cameras.subtitle")} icon="camera" />
          {cameras.isLoading ? (
            <LoadingBlock />
          ) : (cameras.data?.items ?? []).length === 0 ? (
            <EmptyState icon="camera" title={t("settings.cameras.empty_title")} description={t("settings.cameras.empty_description")} action={<Button icon="plus" onClick={() => openCreateCamera()}>{t("settings.add_camera")}</Button>} />
          ) : (
            <TableShell>
              <thead>
                <tr>
                  <Th>{t("settings.table.camera")}</Th>
                  <Th>{t("settings.table.gate")}</Th>
                  <Th>{t("settings.table.source")}</Th>
                  <Th>{t("common.status")}</Th>
                  <Th>{t("settings.table.last_frame")}</Th>
                  <Th align="right">{t("common.actions")}</Th>
                </tr>
              </thead>
              <tbody>
                {(cameras.data?.items ?? []).map((camera) => {
                  const gate = gateOptions.find((item) => item.id === camera.gate_id);
                  const online = camera.status === "online";
                  return (
                    <tr key={camera.id} className="transition hover:bg-ink-50/70 dark:hover:bg-ink-800/30">
                      <Td>
                        <p className="text-sm font-semibold text-ink-900 dark:text-ink-100">{camera.name}</p>
                        <p className="text-[10px] capitalize text-ink-400">{camera.position} · {camera.fps_limit} fps</p>
                      </Td>
                      <Td className="text-xs">{gate?.name ?? "—"}</Td>
                      <Td>
                        <p className="text-[10px] font-semibold uppercase text-ink-400">{camera.source_type}</p>
                        <p className="max-w-[220px] truncate font-mono text-[10px] text-ink-500 dark:text-ink-400">{camera.source_url}</p>
                        {camera.last_error ? (
                          <p className="max-w-[240px] truncate text-[10px] text-rose-500" title={camera.last_error}>
                            {camera.last_error}
                          </p>
                        ) : null}
                      </Td>
                      <Td><Badge tone={online ? "success" : camera.status === "error" ? "danger" : "neutral"} dot>{t(`status.${camera.status}`, {})}</Badge></Td>
                      <Td className="whitespace-nowrap text-[11px] text-ink-500 dark:text-ink-400">
                        {formatDateTime(camera.last_frame_at)}
                        {camera.resolution ? (
                          <p className="font-mono text-[10px] text-ink-400">{camera.resolution}</p>
                        ) : null}
                      </Td>
                      <Td align="right">
                        <div className="flex justify-end gap-1">
                          <Button
                            size="sm"
                            variant="subtle"
                            icon="play"
                            onClick={() => probeMutation.mutate(camera)}
                            loading={probeMutation.isPending && probeMutation.variables?.id === camera.id}
                          >
                            {t("settings.action.test_stream")}
                          </Button>
                          <Button size="sm" variant="ghost" onClick={() => toggleCameraMutation.mutate({ camera, active: !camera.is_active })}>
                            {camera.is_active ? t("common.disable") : t("common.enable")}
                          </Button>
                          <Button size="icon" variant="ghost" onClick={() => openEditCamera(camera)} aria-label={t("settings.action.edit_camera")}><Icon name="edit" className="h-4 w-4" /></Button>
                          <Button size="icon" variant="ghost" onClick={() => setCameraToDelete(camera)} aria-label={t("settings.action.delete_camera")}><Icon name="trash" className="h-4 w-4 text-rose-500" /></Button>
                        </div>
                      </Td>
                    </tr>
                  );
                })}
              </tbody>
            </TableShell>
          )}
        </Card>
        </>
      ) : null}

      {tab === "policy" && isAdmin ? (
        compound ? (
          <CompoundPolicyPanel compoundId={compound.id} />
        ) : (
          <Card>
            <EmptyState
              icon="gate"
              title={t("settings.policy.no_compound_title")}
              description={t("settings.policy.no_compound_desc")}
            />
          </Card>
        )
      ) : null}

      {tab === "users" && isAdmin ? (
        <Card>
          <CardHeader title={t("settings.users.title")} subtitle={t("settings.users.subtitle")} icon="users" />
          {users.isLoading ? (
            <LoadingBlock />
          ) : (
            <TableShell>
              <thead>
                <tr>
                  <Th>{t("settings.table.user")}</Th>
                  <Th>{t("common.role")}</Th>
                  <Th>{t("common.status")}</Th>
                  <Th>{t("settings.table.last_login")}</Th>
                  <Th align="right">{t("common.actions")}</Th>
                </tr>
              </thead>
              <tbody>
                {(users.data?.items ?? []).map((item) => (
                  <tr key={item.id} className="transition hover:bg-ink-50/70 dark:hover:bg-ink-800/30">
                    <Td>
                      <div className="flex items-center gap-3">
                        <span className="grid h-8 w-8 place-items-center rounded-full bg-ink-900 text-[10px] font-bold text-white dark:bg-ink-100 dark:text-ink-900">{initials(item.full_name)}</span>
                        <div>
                          <p className="text-sm font-semibold text-ink-900 dark:text-ink-100">{item.full_name}</p>
                          <p className="text-[10px] text-ink-400">{item.email}</p>
                        </div>
                      </div>
                    </Td>
                    <Td><Badge tone={item.role === "admin" ? "brand" : item.role === "security_officer" ? "info" : "neutral"}>{t(`role.${item.role}`)}</Badge></Td>
                    <Td><Badge tone={item.is_active ? "success" : "neutral"} dot>{item.is_active ? t("common.active") : t("common.disabled")}</Badge></Td>
                    <Td className="text-[11px] text-ink-500 dark:text-ink-400">{formatDateTime(item.last_login_at)}</Td>
                    <Td align="right">
                      <div className="flex justify-end gap-1">
                        <Button size="sm" variant="ghost" icon="key" onClick={() => { setPasswordTarget(item); setNewPassword(""); }}>{t("settings.action.reset")}</Button>
                        <Button size="sm" variant="ghost" onClick={() => {
                          void updateUser(item.id, { is_active: !item.is_active }).then(async () => {
                            toast.success(item.is_active ? t("settings.toast.user_disabled") : t("settings.toast.user_enabled"));
                            await queryClient.invalidateQueries({ queryKey: ["users"] });
                          }).catch((error) => toast.error(t("settings.toast.update_failed"), apiErrorMessage(error)));
                        }}>
                          {item.is_active ? t("common.disable") : t("common.enable")}
                        </Button>
                        {item.is_active ? (
                          <Button size="icon" variant="ghost" onClick={() => setUserToDeactivate(item)} aria-label={t("settings.action.deactivate_user")}><Icon name="trash" className="h-4 w-4 text-rose-500" /></Button>
                        ) : null}
                      </div>
                    </Td>
                  </tr>
                ))}
              </tbody>
            </TableShell>
          )}
        </Card>
      ) : null}

      {tab === "account" ? (
        <div className="grid gap-4 xl:grid-cols-2">
          <Card>
            <CardHeader title={t("settings.profile.title")} subtitle={t("settings.profile.subtitle")} icon="users" />
            <div className="flex items-center gap-4 p-5">
              <span className="grid h-14 w-14 place-items-center rounded-2xl bg-gradient-to-br from-brand-500 to-brand-700 text-lg font-bold text-white">{initials(user?.full_name)}</span>
              <div>
                <p className="text-base font-semibold">{user?.full_name}</p>
                <p className="text-xs text-ink-500 dark:text-ink-400">{user?.email}</p>
                <div className="mt-1.5 flex gap-2">
                  <Badge tone="brand">{user ? t(`role.${user.role}`) : ""}</Badge>
                  <Badge tone={user?.is_active ? "success" : "neutral"} dot>{user?.is_active ? t("common.active") : t("common.disabled")}</Badge>
                </div>
              </div>
            </div>
            <form
              className="space-y-3 border-t border-ink-100 p-5 dark:border-ink-800"
              onSubmit={(event) => { event.preventDefault(); accountMutation.mutate(); }}
            >
              <p className="text-xs font-semibold text-ink-800 dark:text-ink-100">{t("settings.account.change_password")}</p>
              <Input label={t("settings.account.current")} type="password" required value={accountForm.current} onChange={(event) => setAccountForm({ ...accountForm, current: event.target.value })} />
              <div className="grid gap-3 sm:grid-cols-2">
                <Input label={t("settings.account.new")} type="password" required value={accountForm.next} onChange={(event) => setAccountForm({ ...accountForm, next: event.target.value })} hint={t("settings.account.password_hint")} />
                <Input label={t("settings.account.confirm")} type="password" required value={accountForm.confirm} onChange={(event) => setAccountForm({ ...accountForm, confirm: event.target.value })} error={accountForm.confirm && accountForm.confirm !== accountForm.next ? t("settings.account.password_mismatch") : undefined} />
              </div>
              <Button type="submit" icon="key" loading={accountMutation.isPending} disabled={!accountForm.current || accountForm.next.length < 8 || accountForm.next !== accountForm.confirm}>
                {t("settings.account.update")}
              </Button>
            </form>
          </Card>

          {!compound && isAdmin ? (
            <Card>
              <CardHeader
                title={t("settings.compound.create_title")}
                subtitle={t("settings.compound.create_subtitle")}
                icon="gate"
              />
              <div className="space-y-4 p-5">
                <div className="grid gap-3 sm:grid-cols-2">
                  <Input
                    label={t("settings.compound.name")}
                    required
                    value={compoundForm.name}
                    onChange={(event) => setCompoundForm({ ...compoundForm, name: event.target.value })}
                    placeholder="Palm Hills"
                  />
                  <Input
                    label={t("common.code")}
                    required
                    value={compoundForm.code}
                    onChange={(event) =>
                      setCompoundForm({ ...compoundForm, code: event.target.value.toUpperCase() })
                    }
                    placeholder="PALM-HILLS"
                    className="font-mono"
                  />
                  <Input
                    label={t("settings.compound.city")}
                    value={compoundForm.city}
                    onChange={(event) => setCompoundForm({ ...compoundForm, city: event.target.value })}
                    placeholder="Cairo"
                  />
                  <Input
                    label={t("settings.compound.phone")}
                    value={compoundForm.contact_phone}
                    onChange={(event) =>
                      setCompoundForm({ ...compoundForm, contact_phone: event.target.value })
                    }
                    placeholder="+20 100 000 0000"
                  />
                  <Input
                    label={t("settings.compound.email")}
                    value={compoundForm.contact_email}
                    onChange={(event) =>
                      setCompoundForm({ ...compoundForm, contact_email: event.target.value })
                    }
                    placeholder="security@compound.eg"
                    className="sm:col-span-2"
                  />
                </div>
                <Button
                  icon="plus"
                  onClick={() => createCompoundMutation.mutate()}
                  loading={createCompoundMutation.isPending}
                  disabled={compoundForm.name.trim().length < 2 || compoundForm.code.trim().length < 2}
                >
                  {t("settings.compound.create")}
                </Button>
              </div>
            </Card>
          ) : null}

          <Card>
            <CardHeader title={t("settings.compound.title")} subtitle={isAdmin ? t("settings.compound.subtitle") : t("settings.compound.subtitle_readonly")} icon="gate" />
            <div className="space-y-4 p-5">
              <div className="grid gap-3 sm:grid-cols-2">
                <Input label={t("settings.compound.name")} value={isAdmin ? compoundForm.name || compound?.name || "" : compound?.name ?? ""} onChange={(event) => setCompoundForm({ ...compoundForm, name: event.target.value })} disabled={!isAdmin} />
                <Input label={t("settings.compound.city")} value={isAdmin ? compoundForm.city || compound?.city || "" : compound?.city ?? ""} onChange={(event) => setCompoundForm({ ...compoundForm, city: event.target.value })} disabled={!isAdmin} />
                <Input label={t("settings.compound.phone")} value={isAdmin ? compoundForm.contact_phone || compound?.contact_phone || "" : compound?.contact_phone ?? ""} onChange={(event) => setCompoundForm({ ...compoundForm, contact_phone: event.target.value })} disabled={!isAdmin} />
                <Input label={t("settings.compound.email")} value={isAdmin ? compoundForm.contact_email || compound?.contact_email || "" : compound?.contact_email ?? ""} onChange={(event) => setCompoundForm({ ...compoundForm, contact_email: event.target.value })} disabled={!isAdmin} />
              </div>
              <dl className="grid gap-2 rounded-xl bg-ink-50 p-4 text-xs sm:grid-cols-2 dark:bg-ink-900">
                <div className="flex justify-between gap-2"><dt className="text-ink-500">{t("common.code")}</dt><dd className="font-mono font-semibold">{compound?.code ?? "—"}</dd></div>
                <div className="flex justify-between gap-2"><dt className="text-ink-500">{t("settings.compound.timezone")}</dt><dd className="font-semibold">{compound?.timezone ?? "—"}</dd></div>
                <div className="flex justify-between gap-2"><dt className="text-ink-500">{t("settings.tab.gates")}</dt><dd className="font-semibold">{gateOptions.length}</dd></div>
                <div className="flex justify-between gap-2"><dt className="text-ink-500">{t("settings.tab.cameras")}</dt><dd className="font-semibold">{cameras.data?.total ?? "—"}</dd></div>
              </dl>
              {isAdmin ? (
                <Button icon="check" onClick={() => compoundMutation.mutate()} loading={compoundMutation.isPending}>
                  {t("settings.compound.save")}
                </Button>
              ) : null}
            </div>
          </Card>
        </div>
      ) : null}

      <Modal
        open={gateOpen}
        onClose={() => setGateOpen(false)}
        title={editingGate ? t("settings.gate.edit_title") : t("settings.gate.create_title")}
        footer={
          <>
            <Button variant="outline" onClick={() => setGateOpen(false)}>{t("common.cancel")}</Button>
            <Button onClick={() => gateMutation.mutate()} loading={gateMutation.isPending} disabled={!gateForm.name.trim() || !gateForm.code.trim()}>
              {editingGate ? t("common.save_changes") : t("settings.gate.create")}
            </Button>
          </>
        }
      >
        <div className="grid gap-4 sm:grid-cols-2">
          <Input label={t("common.name")} required value={gateForm.name} onChange={(event) => setGateForm({ ...gateForm, name: event.target.value })} placeholder={t("settings.gate.name_placeholder")} />
          <Input label={t("common.code")} required value={gateForm.code} onChange={(event) => setGateForm({ ...gateForm, code: event.target.value.toUpperCase() })} placeholder="GATE-IN" className="font-mono" disabled={Boolean(editingGate)} />
          <Select label={t("common.direction")} value={gateForm.direction} onChange={(event) => setGateForm({ ...gateForm, direction: event.target.value as GateDirection })}>
            <option value="entry">{t("direction.entry")}</option>
            <option value="exit">{t("direction.exit")}</option>
            <option value="bidirectional">{t("direction.bidirectional")}</option>
          </Select>
          <Select label={t("common.status")} value={gateForm.status} onChange={(event) => setGateForm({ ...gateForm, status: event.target.value as GateStatus })}>
            <option value="online">{t("status.online")}</option>
            <option value="maintenance">{t("status.maintenance")}</option>
            <option value="offline">{t("status.offline")}</option>
          </Select>
          <Input label={t("settings.table.location")} value={gateForm.location ?? ""} onChange={(event) => setGateForm({ ...gateForm, location: event.target.value })} className="sm:col-span-2" placeholder={t("settings.gate.location_placeholder")} />
          <Textarea label={t("common.notes")} value={gateForm.notes ?? ""} onChange={(event) => setGateForm({ ...gateForm, notes: event.target.value })} className="sm:col-span-2" />
        </div>
      </Modal>

      <Modal
        open={cameraOpen}
        onClose={() => setCameraOpen(false)}
        title={editingCamera ? t("settings.camera.edit_title") : t("settings.camera.create_title")}
        description={t("settings.camera.description")}
        footer={
          <>
            <Button variant="outline" onClick={() => setCameraOpen(false)}>{t("common.cancel")}</Button>
            <Button
              onClick={() => cameraMutation.mutate()}
              loading={cameraMutation.isPending}
              disabled={
                !cameraForm.name.trim() ||
                (!editingCamera && !cameraForm.source_url.trim()) ||
                !cameraForm.gate_id
              }
            >
              {editingCamera ? t("common.save_changes") : t("settings.add_camera")}
            </Button>
          </>
        }
      >
        <div className="grid gap-4 sm:grid-cols-2">
          <Input label="Name" required value={cameraForm.name} onChange={(event) => setCameraForm({ ...cameraForm, name: event.target.value })} placeholder={t("settings.camera.name_placeholder")} />
          <Select label={t("settings.table.gate")} value={cameraForm.gate_id} onChange={(event) => setCameraForm({ ...cameraForm, gate_id: event.target.value })}>
            <option value="">{t("settings.camera.select_gate")}</option>
            {gateOptions.map((gate) => (
              <option key={gate.id} value={gate.id}>{gate.name}</option>
            ))}
          </Select>
          <Select label={t("settings.camera.source_type")} value={cameraForm.source_type} onChange={(event) => setCameraForm({ ...cameraForm, source_type: event.target.value as CameraSourceType })}>
            <option value="rtsp">RTSP</option>
            <option value="usb">{t("settings.camera.source_usb")}</option>
            <option value="file">{t("settings.camera.source_file")}</option>
            <option value="demo">{t("settings.camera.source_demo")}</option>
          </Select>
          <Input
            label={t("settings.camera.source_url")}
            required={!editingCamera}
            value={cameraForm.source_url}
            onChange={(event) => setCameraForm({ ...cameraForm, source_url: event.target.value })}
            placeholder={editingCamera?.source_url ?? "rtsp://user:password@10.0.0.11:554/Streaming/Channels/101"}
            hint={
              editingCamera
                ? t("settings.camera.source_url_keep_hint")
                : t("settings.camera.source_url_hint")
            }
            className="sm:col-span-2 font-mono"
          />
          <Input label={t("settings.camera.fps")} type="number" min={1} max={30} value={cameraForm.fps_limit ?? 5} onChange={(event) => setCameraForm({ ...cameraForm, fps_limit: Number(event.target.value) })} />
          <Input label={t("settings.camera.position")} value={cameraForm.position} onChange={(event) => setCameraForm({ ...cameraForm, position: event.target.value })} placeholder="front" />
          <Textarea label={t("common.notes")} value={cameraForm.notes ?? ""} onChange={(event) => setCameraForm({ ...cameraForm, notes: event.target.value })} className="sm:col-span-2" />
        </div>
      </Modal>

      <Modal
        open={userOpen}
        onClose={() => setUserOpen(false)}
        title={t("settings.user.modal_title")}
        footer={
          <>
            <Button variant="outline" onClick={() => setUserOpen(false)}>{t("common.cancel")}</Button>
            <Button onClick={() => userMutation.mutate()} loading={userMutation.isPending} disabled={!userForm.email.trim() || !userForm.full_name.trim() || userForm.password.length < 8}>
              {t("settings.create_user")}
            </Button>
          </>
        }
      >
        <div className="grid gap-4 sm:grid-cols-2">
          <Input label={t("settings.user.full_name")} required value={userForm.full_name} onChange={(event) => setUserForm({ ...userForm, full_name: event.target.value })} />
          <Input label={t("common.email")} type="email" required value={userForm.email} onChange={(event) => setUserForm({ ...userForm, email: event.target.value })} />
          <Input label={t("settings.user.temporary")} type="password" required value={userForm.password} onChange={(event) => setUserForm({ ...userForm, password: event.target.value })} hint={t("settings.user.temp_hint")} />
          <Select label={t("common.role")} value={userForm.role} onChange={(event) => setUserForm({ ...userForm, role: event.target.value as UserRole })}>
            <option value="security_officer">{t("role.security_officer")}</option>
            <option value="admin">{t("role.admin")}</option>
            <option value="resident">{t("role.resident")}</option>
          </Select>
          <Input label={t("common.phone")} value={userForm.phone} onChange={(event) => setUserForm({ ...userForm, phone: event.target.value })} className="sm:col-span-2" />
        </div>
      </Modal>

      <Modal
        open={passwordTarget !== null}
        onClose={() => setPasswordTarget(null)}
        title={t("settings.password.reset_title")}
        description={passwordTarget ? t("settings.password.reset_description", { name: passwordTarget.full_name }) : undefined}
        size="sm"
        footer={
          <>
            <Button variant="outline" onClick={() => setPasswordTarget(null)}>{t("common.cancel")}</Button>
            <Button onClick={() => passwordTarget && resetPasswordMutation.mutate({ id: passwordTarget.id, password: newPassword })} loading={resetPasswordMutation.isPending} disabled={newPassword.length < 8}>
              {t("settings.password.reset_action")}
            </Button>
          </>
        }
      >
        <Input label={t("settings.account.new")} type="password" value={newPassword} onChange={(event) => setNewPassword(event.target.value)} hint={t("settings.password.hint")} />
      </Modal>

      <Modal
        open={probe !== null}
        onClose={() => setProbe(null)}
        title={t("settings.probe.title")}
        description={probe?.camera.name}
        footer={
          <Button variant="outline" onClick={() => setProbe(null)}>
            {t("common.close")}
          </Button>
        }
      >
        {probe?.result ? (
          <div className="space-y-3">
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone={probe.result.ok ? "success" : "danger"} dot>
                {probe.result.ok ? t("settings.probe.ok") : t("settings.probe.failed")}
              </Badge>
              <Badge tone="neutral">
                {t("settings.probe.latency", { value: probe.result.latency_ms })}
              </Badge>
              {probe.result.width && probe.result.height ? (
                <Badge tone="info">{`${probe.result.width}×${probe.result.height}`}</Badge>
              ) : null}
              {probe.result.brightness !== null ? (
                <Badge tone={probe.result.brightness < 70 ? "warning" : "neutral"}>
                  {t("settings.probe.brightness", { value: Math.round(probe.result.brightness) })}
                </Badge>
              ) : null}
            </div>
            {probe.result.preview_url ? (
              <img
                src={probe.result.preview_url}
                alt={t("settings.probe.preview")}
                className="w-full rounded-xl border border-ink-200 object-cover dark:border-ink-700"
              />
            ) : null}
            <p className="font-mono text-[10px] break-all text-ink-400">{probe.result.source}</p>
            {probe.result.error ? (
              <div className="rounded-xl border border-rose-200 bg-rose-50/70 p-3 text-xs text-rose-800 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-200">
                <p className="font-semibold">{probe.result.error}</p>
                {probe.result.hint ? <p className="mt-1 leading-relaxed">{probe.result.hint}</p> : null}
              </div>
            ) : null}
          </div>
        ) : (
          <p className="text-xs text-ink-500 dark:text-ink-400">{t("settings.probe.no_result")}</p>
        )}
      </Modal>

      <ConfirmDialog
        open={gateToDelete !== null}
        onClose={() => setGateToDelete(null)}
        onConfirm={() => gateToDelete && deleteGateMutation.mutate(gateToDelete)}
        loading={deleteGateMutation.isPending}
        title={t("settings.delete_gate.title")}
        description={t("settings.delete_gate.description", { name: gateToDelete?.name ?? t("settings.table.gate") })}
        confirmLabel={t("settings.delete_gate.confirm")}
      />

      <ConfirmDialog
        open={cameraToDelete !== null}
        onClose={() => setCameraToDelete(null)}
        onConfirm={() => cameraToDelete && deleteCameraMutation.mutate(cameraToDelete)}
        loading={deleteCameraMutation.isPending}
        title={t("settings.delete_camera.title")}
        description={t("settings.delete_camera.description", { name: cameraToDelete?.name ?? t("settings.table.camera") })}
        confirmLabel={t("settings.delete_camera.confirm")}
      />

      <ConfirmDialog
        open={userToDeactivate !== null}
        onClose={() => setUserToDeactivate(null)}
        onConfirm={() => userToDeactivate && deactivateMutation.mutate(userToDeactivate)}
        loading={deactivateMutation.isPending}
        title={t("settings.deactivate.title")}
        description={t("settings.deactivate.description", { name: userToDeactivate?.full_name ?? t("settings.table.user") })}
        confirmLabel={t("settings.deactivate.confirm")}
      />
    </div>
  );
}
