import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

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
import { useToast } from "@/hooks/useToast";
import {
  createCamera,
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
import type {
  Camera,
  CameraSourceType,
  Gate,
  GateDirection,
  GateStatus,
  User,
  UserRole,
} from "@/types/models";
import { GATE_STATUS_META, ROLE_LABELS } from "@/utils/constants";
import { formatDateTime, initials } from "@/utils/format";

type TabKey = "gates" | "cameras" | "users" | "account";

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

  const [userOpen, setUserOpen] = useState(false);
  const [userForm, setUserForm] = useState(EMPTY_USER);
  const [userToDeactivate, setUserToDeactivate] = useState<User | null>(null);
  const [passwordTarget, setPasswordTarget] = useState<User | null>(null);
  const [newPassword, setNewPassword] = useState("");

  const [compoundForm, setCompoundForm] = useState({ name: "", city: "", contact_phone: "", contact_email: "" });
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
      if (!compound) throw new Error("No compound available");
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
      toast.success(editingGate ? "Gate updated" : "Gate created");
      setGateOpen(false);
      setEditingGate(null);
      setGateForm(EMPTY_GATE);
      await invalidate();
    },
    onError: (error) => toast.error("Could not save gate", apiErrorMessage(error)),
  });

  const cameraMutation = useMutation({
    mutationFn: async (): Promise<void> => {
      if (!cameraForm.gate_id) throw new Error("Select a gate");
      if (editingCamera) {
        await updateCamera(editingCamera.id, {
          name: cameraForm.name,
          source_type: cameraForm.source_type,
          source_url: cameraForm.source_url,
          fps_limit: cameraForm.fps_limit,
          position: cameraForm.position,
          notes: cameraForm.notes,
        });
      } else {
        await createCamera(cameraForm);
      }
    },
    onSuccess: async () => {
      toast.success(editingCamera ? "Camera updated" : "Camera added");
      setCameraOpen(false);
      setEditingCamera(null);
      setCameraForm(EMPTY_CAMERA);
      await invalidate();
    },
    onError: (error) => toast.error("Could not save camera", apiErrorMessage(error)),
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
      toast.success("User created");
      setUserOpen(false);
      setUserForm(EMPTY_USER);
      await invalidate();
    },
    onError: (error) => toast.error("Could not create user", apiErrorMessage(error)),
  });

  const resetPasswordMutation = useMutation({
    mutationFn: ({ id, password }: { id: string; password: string }) => resetUserPassword(id, password),
    onSuccess: () => {
      toast.success("Password reset");
      setPasswordTarget(null);
      setNewPassword("");
    },
    onError: (error) => toast.error("Could not reset password", apiErrorMessage(error)),
  });

  const deactivateMutation = useMutation({
    mutationFn: (target: User) => deactivateUser(target.id),
    onSuccess: async () => {
      toast.success("User deactivated");
      setUserToDeactivate(null);
      await invalidate();
    },
    onError: (error) => toast.error("Could not deactivate user", apiErrorMessage(error)),
  });

  const toggleCameraMutation = useMutation({
    mutationFn: ({ camera, active }: { camera: Camera; active: boolean }) => toggleCamera(camera.id, active),
    onSuccess: async (camera) => {
      toast.success(`Camera ${camera.status}`);
      await invalidate();
    },
    onError: (error) => toast.error("Could not toggle camera", apiErrorMessage(error)),
  });

  const deleteCameraMutation = useMutation({
    mutationFn: (camera: Camera) => deleteCamera(camera.id),
    onSuccess: async () => {
      toast.success("Camera deleted");
      setCameraToDelete(null);
      await invalidate();
    },
    onError: (error) => toast.error("Could not delete camera", apiErrorMessage(error)),
  });

  const deleteGateMutation = useMutation({
    mutationFn: (gate: Gate) => deleteGate(gate.id),
    onSuccess: async () => {
      toast.success("Gate deleted");
      setGateToDelete(null);
      await invalidate();
    },
    onError: (error) => toast.error("Could not delete gate", apiErrorMessage(error)),
  });

  const commandMutation = useMutation({
    mutationFn: (gate: Gate) => gateCommand(gate.id, "open", "Opened from settings"),
    onSuccess: (result) => toast.success("Barrier command accepted", result.detail),
    onError: (error) => toast.error("Command failed", apiErrorMessage(error)),
  });

  const compoundMutation = useMutation({
    mutationFn: async (): Promise<void> => {
      if (!compound) throw new Error("No compound available");
      await updateCompound(compound.id, {
        name: compoundForm.name || compound.name,
        city: compoundForm.city || compound.city,
        contact_phone: compoundForm.contact_phone || compound.contact_phone,
        contact_email: compoundForm.contact_email || compound.contact_email,
      });
    },
    onSuccess: async () => {
      toast.success("Compound updated");
      await invalidate();
    },
    onError: (error) => toast.error("Could not update compound", apiErrorMessage(error)),
  });

  const accountMutation = useMutation({
    mutationFn: async (): Promise<void> => {
      if (accountForm.next !== accountForm.confirm) throw new Error("Passwords do not match");
      await changePassword(accountForm.current, accountForm.next);
    },
    onSuccess: () => {
      toast.success("Password changed");
      setAccountForm({ current: "", next: "", confirm: "" });
    },
    onError: (error) => toast.error("Could not change password", apiErrorMessage(error)),
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
      source_url: camera.source_url,
      fps_limit: camera.fps_limit,
      position: camera.position,
      notes: camera.notes ?? "",
    });
    setCameraOpen(true);
  };

  const tabs: { key: TabKey; label: string }[] = [
    ...(isManager ? [{ key: "gates" as TabKey, label: "Gates" }] : []),
    ...(isManager ? [{ key: "cameras" as TabKey, label: "Cameras" }] : []),
    ...(isAdmin ? [{ key: "users" as TabKey, label: "Users" }] : []),
    { key: "account", label: "Account & compound" },
  ];

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Configuration"
        title="Settings"
        subtitle="Physical gates, camera sources, staff accounts and compound details."
        actions={
          tab === "gates" ? (
            <Button icon="plus" onClick={openCreateGate}>Add gate</Button>
          ) : tab === "cameras" ? (
            <Button icon="plus" onClick={() => openCreateCamera()}>Add camera</Button>
          ) : tab === "users" ? (
            <Button icon="plus" onClick={() => setUserOpen(true)}>Create user</Button>
          ) : null
        }
      />

      <Tabs tabs={tabs} value={tab} onChange={setTab} />

      {tab === "gates" ? (
        <Card>
          <CardHeader title="Gates" subtitle="Entry, exit and service lanes for the compound" icon="gate" />
          {gates.isLoading ? (
            <LoadingBlock />
          ) : gateOptions.length === 0 ? (
            <EmptyState icon="gate" title="No gates configured" description="Create the first gate to connect cameras and barriers." action={<Button icon="plus" onClick={openCreateGate}>Add gate</Button>} />
          ) : (
            <TableShell>
              <thead>
                <tr>
                  <Th>Gate</Th>
                  <Th>Direction</Th>
                  <Th>Status</Th>
                  <Th>Cameras</Th>
                  <Th>Location</Th>
                  <Th align="right">Actions</Th>
                </tr>
              </thead>
              <tbody>
                {gateOptions.map((gate) => (
                  <tr key={gate.id} className="transition hover:bg-ink-50/70 dark:hover:bg-ink-800/30">
                    <Td>
                      <p className="text-sm font-semibold text-ink-900 dark:text-ink-100">{gate.name}</p>
                      <p className="font-mono text-[10px] text-ink-400">{gate.code}</p>
                    </Td>
                    <Td className="text-xs capitalize">{gate.direction}</Td>
                    <Td><Badge tone={GATE_STATUS_META[gate.status].tone} dot>{GATE_STATUS_META[gate.status].label}</Badge></Td>
                    <Td className="text-xs">{gate.cameras.length}</Td>
                    <Td className="text-xs">{gate.location ?? "—"}</Td>
                    <Td align="right">
                      <div className="flex justify-end gap-1">
                        <Button size="sm" variant="subtle" icon="play" onClick={() => commandMutation.mutate(gate)}>Open</Button>
                        <Button size="icon" variant="ghost" onClick={() => openCreateCamera(gate.id)} aria-label="Add camera"><Icon name="camera" className="h-4 w-4" /></Button>
                        <Button size="icon" variant="ghost" onClick={() => openEditGate(gate)} aria-label="Edit gate"><Icon name="edit" className="h-4 w-4" /></Button>
                        {isAdmin ? (
                          <Button size="icon" variant="ghost" onClick={() => setGateToDelete(gate)} aria-label="Delete gate"><Icon name="trash" className="h-4 w-4 text-rose-500" /></Button>
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
        <Card>
          <CardHeader title="Cameras" subtitle="RTSP, USB and demo sources feeding the vision pipeline" icon="camera" />
          {cameras.isLoading ? (
            <LoadingBlock />
          ) : (cameras.data?.items ?? []).length === 0 ? (
            <EmptyState icon="camera" title="No cameras connected" description="Add a stream so the gate controller can see vehicles." action={<Button icon="plus" onClick={() => openCreateCamera()}>Add camera</Button>} />
          ) : (
            <TableShell>
              <thead>
                <tr>
                  <Th>Camera</Th>
                  <Th>Gate</Th>
                  <Th>Source</Th>
                  <Th>Status</Th>
                  <Th>Last frame</Th>
                  <Th align="right">Actions</Th>
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
                      </Td>
                      <Td><Badge tone={online ? "success" : camera.status === "error" ? "danger" : "neutral"} dot>{camera.status}</Badge></Td>
                      <Td className="whitespace-nowrap text-[11px] text-ink-500 dark:text-ink-400">{formatDateTime(camera.last_frame_at)}</Td>
                      <Td align="right">
                        <div className="flex justify-end gap-1">
                          <Button size="sm" variant="ghost" onClick={() => toggleCameraMutation.mutate({ camera, active: !camera.is_active })}>
                            {camera.is_active ? "Disable" : "Enable"}
                          </Button>
                          <Button size="icon" variant="ghost" onClick={() => openEditCamera(camera)} aria-label="Edit camera"><Icon name="edit" className="h-4 w-4" /></Button>
                          <Button size="icon" variant="ghost" onClick={() => setCameraToDelete(camera)} aria-label="Delete camera"><Icon name="trash" className="h-4 w-4 text-rose-500" /></Button>
                        </div>
                      </Td>
                    </tr>
                  );
                })}
              </tbody>
            </TableShell>
          )}
        </Card>
      ) : null}

      {tab === "users" && isAdmin ? (
        <Card>
          <CardHeader title="Staff accounts" subtitle="Administrators and security officers" icon="users" />
          {users.isLoading ? (
            <LoadingBlock />
          ) : (
            <TableShell>
              <thead>
                <tr>
                  <Th>User</Th>
                  <Th>Role</Th>
                  <Th>Status</Th>
                  <Th>Last login</Th>
                  <Th align="right">Actions</Th>
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
                    <Td><Badge tone={item.role === "admin" ? "brand" : item.role === "security_officer" ? "info" : "neutral"}>{ROLE_LABELS[item.role]}</Badge></Td>
                    <Td><Badge tone={item.is_active ? "success" : "neutral"} dot>{item.is_active ? "Active" : "Disabled"}</Badge></Td>
                    <Td className="text-[11px] text-ink-500 dark:text-ink-400">{formatDateTime(item.last_login_at)}</Td>
                    <Td align="right">
                      <div className="flex justify-end gap-1">
                        <Button size="sm" variant="ghost" icon="key" onClick={() => { setPasswordTarget(item); setNewPassword(""); }}>Reset</Button>
                        <Button size="sm" variant="ghost" onClick={() => {
                          void updateUser(item.id, { is_active: !item.is_active }).then(async () => {
                            toast.success(item.is_active ? "User disabled" : "User enabled");
                            await queryClient.invalidateQueries({ queryKey: ["users"] });
                          }).catch((error) => toast.error("Update failed", apiErrorMessage(error)));
                        }}>
                          {item.is_active ? "Disable" : "Enable"}
                        </Button>
                        {item.is_active ? (
                          <Button size="icon" variant="ghost" onClick={() => setUserToDeactivate(item)} aria-label="Deactivate user"><Icon name="trash" className="h-4 w-4 text-rose-500" /></Button>
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
            <CardHeader title="Your profile" subtitle="Account details and role" icon="users" />
            <div className="flex items-center gap-4 p-5">
              <span className="grid h-14 w-14 place-items-center rounded-2xl bg-gradient-to-br from-brand-500 to-brand-700 text-lg font-bold text-white">{initials(user?.full_name)}</span>
              <div>
                <p className="text-base font-semibold">{user?.full_name}</p>
                <p className="text-xs text-ink-500 dark:text-ink-400">{user?.email}</p>
                <div className="mt-1.5 flex gap-2">
                  <Badge tone="brand">{user ? ROLE_LABELS[user.role] : ""}</Badge>
                  <Badge tone={user?.is_active ? "success" : "neutral"} dot>{user?.is_active ? "Active" : "Disabled"}</Badge>
                </div>
              </div>
            </div>
            <form
              className="space-y-3 border-t border-ink-100 p-5 dark:border-ink-800"
              onSubmit={(event) => { event.preventDefault(); accountMutation.mutate(); }}
            >
              <p className="text-xs font-semibold text-ink-800 dark:text-ink-100">Change password</p>
              <Input label="Current password" type="password" required value={accountForm.current} onChange={(event) => setAccountForm({ ...accountForm, current: event.target.value })} />
              <div className="grid gap-3 sm:grid-cols-2">
                <Input label="New password" type="password" required value={accountForm.next} onChange={(event) => setAccountForm({ ...accountForm, next: event.target.value })} hint="At least 8 characters with a letter and a digit" />
                <Input label="Confirm password" type="password" required value={accountForm.confirm} onChange={(event) => setAccountForm({ ...accountForm, confirm: event.target.value })} error={accountForm.confirm && accountForm.confirm !== accountForm.next ? "Passwords do not match" : undefined} />
              </div>
              <Button type="submit" icon="key" loading={accountMutation.isPending} disabled={!accountForm.current || accountForm.next.length < 8 || accountForm.next !== accountForm.confirm}>
                Update password
              </Button>
            </form>
          </Card>

          <Card>
            <CardHeader title="Compound profile" subtitle={isAdmin ? "Details shown across the dashboard" : "Read-only for your role"} icon="gate" />
            <div className="space-y-4 p-5">
              <div className="grid gap-3 sm:grid-cols-2">
                <Input label="Compound" value={isAdmin ? compoundForm.name || compound?.name || "" : compound?.name ?? ""} onChange={(event) => setCompoundForm({ ...compoundForm, name: event.target.value })} disabled={!isAdmin} />
                <Input label="City" value={isAdmin ? compoundForm.city || compound?.city || "" : compound?.city ?? ""} onChange={(event) => setCompoundForm({ ...compoundForm, city: event.target.value })} disabled={!isAdmin} />
                <Input label="Contact phone" value={isAdmin ? compoundForm.contact_phone || compound?.contact_phone || "" : compound?.contact_phone ?? ""} onChange={(event) => setCompoundForm({ ...compoundForm, contact_phone: event.target.value })} disabled={!isAdmin} />
                <Input label="Contact email" value={isAdmin ? compoundForm.contact_email || compound?.contact_email || "" : compound?.contact_email ?? ""} onChange={(event) => setCompoundForm({ ...compoundForm, contact_email: event.target.value })} disabled={!isAdmin} />
              </div>
              <dl className="grid gap-2 rounded-xl bg-ink-50 p-4 text-xs sm:grid-cols-2 dark:bg-ink-900">
                <div className="flex justify-between gap-2"><dt className="text-ink-500">Code</dt><dd className="font-mono font-semibold">{compound?.code ?? "—"}</dd></div>
                <div className="flex justify-between gap-2"><dt className="text-ink-500">Timezone</dt><dd className="font-semibold">{compound?.timezone ?? "—"}</dd></div>
                <div className="flex justify-between gap-2"><dt className="text-ink-500">Gates</dt><dd className="font-semibold">{gateOptions.length}</dd></div>
                <div className="flex justify-between gap-2"><dt className="text-ink-500">Cameras</dt><dd className="font-semibold">{cameras.data?.total ?? "—"}</dd></div>
              </dl>
              {isAdmin ? (
                <Button icon="check" onClick={() => compoundMutation.mutate()} loading={compoundMutation.isPending}>
                  Save compound
                </Button>
              ) : null}
            </div>
          </Card>
        </div>
      ) : null}

      <Modal
        open={gateOpen}
        onClose={() => setGateOpen(false)}
        title={editingGate ? "Edit gate" : "Add a gate"}
        footer={
          <>
            <Button variant="outline" onClick={() => setGateOpen(false)}>Cancel</Button>
            <Button onClick={() => gateMutation.mutate()} loading={gateMutation.isPending} disabled={!gateForm.name.trim() || !gateForm.code.trim()}>
              {editingGate ? "Save changes" : "Create gate"}
            </Button>
          </>
        }
      >
        <div className="grid gap-4 sm:grid-cols-2">
          <Input label="Name" required value={gateForm.name} onChange={(event) => setGateForm({ ...gateForm, name: event.target.value })} placeholder="Main entrance" />
          <Input label="Code" required value={gateForm.code} onChange={(event) => setGateForm({ ...gateForm, code: event.target.value.toUpperCase() })} placeholder="GATE-IN" className="font-mono" disabled={Boolean(editingGate)} />
          <Select label="Direction" value={gateForm.direction} onChange={(event) => setGateForm({ ...gateForm, direction: event.target.value as GateDirection })}>
            <option value="entry">Entry</option>
            <option value="exit">Exit</option>
            <option value="bidirectional">Bidirectional</option>
          </Select>
          <Select label="Status" value={gateForm.status} onChange={(event) => setGateForm({ ...gateForm, status: event.target.value as GateStatus })}>
            <option value="online">Online</option>
            <option value="maintenance">Maintenance</option>
            <option value="offline">Offline</option>
          </Select>
          <Input label="Location" value={gateForm.location ?? ""} onChange={(event) => setGateForm({ ...gateForm, location: event.target.value })} className="sm:col-span-2" placeholder="North perimeter" />
          <Textarea label="Notes" value={gateForm.notes ?? ""} onChange={(event) => setGateForm({ ...gateForm, notes: event.target.value })} className="sm:col-span-2" />
        </div>
      </Modal>

      <Modal
        open={cameraOpen}
        onClose={() => setCameraOpen(false)}
        title={editingCamera ? "Edit camera" : "Add a camera"}
        description="RTSP URLs should include credentials when required, e.g. rtsp://user:pass@host/stream."
        footer={
          <>
            <Button variant="outline" onClick={() => setCameraOpen(false)}>Cancel</Button>
            <Button onClick={() => cameraMutation.mutate()} loading={cameraMutation.isPending} disabled={!cameraForm.name.trim() || !cameraForm.source_url.trim() || !cameraForm.gate_id}>
              {editingCamera ? "Save changes" : "Add camera"}
            </Button>
          </>
        }
      >
        <div className="grid gap-4 sm:grid-cols-2">
          <Input label="Name" required value={cameraForm.name} onChange={(event) => setCameraForm({ ...cameraForm, name: event.target.value })} placeholder="Entry lane camera" />
          <Select label="Gate" value={cameraForm.gate_id} onChange={(event) => setCameraForm({ ...cameraForm, gate_id: event.target.value })}>
            <option value="">Select a gate…</option>
            {gateOptions.map((gate) => (
              <option key={gate.id} value={gate.id}>{gate.name}</option>
            ))}
          </Select>
          <Select label="Source type" value={cameraForm.source_type} onChange={(event) => setCameraForm({ ...cameraForm, source_type: event.target.value as CameraSourceType })}>
            <option value="rtsp">RTSP</option>
            <option value="usb">USB camera</option>
            <option value="file">Video file</option>
            <option value="demo">Demo feed</option>
          </Select>
          <Input label="Source URL / index" required value={cameraForm.source_url} onChange={(event) => setCameraForm({ ...cameraForm, source_url: event.target.value })} placeholder="rtsp://… or 0" />
          <Input label="FPS limit" type="number" min={1} max={30} value={cameraForm.fps_limit ?? 5} onChange={(event) => setCameraForm({ ...cameraForm, fps_limit: Number(event.target.value) })} />
          <Input label="Position" value={cameraForm.position} onChange={(event) => setCameraForm({ ...cameraForm, position: event.target.value })} placeholder="front" />
          <Textarea label="Notes" value={cameraForm.notes ?? ""} onChange={(event) => setCameraForm({ ...cameraForm, notes: event.target.value })} className="sm:col-span-2" />
        </div>
      </Modal>

      <Modal
        open={userOpen}
        onClose={() => setUserOpen(false)}
        title="Create a staff account"
        footer={
          <>
            <Button variant="outline" onClick={() => setUserOpen(false)}>Cancel</Button>
            <Button onClick={() => userMutation.mutate()} loading={userMutation.isPending} disabled={!userForm.email.trim() || !userForm.full_name.trim() || userForm.password.length < 8}>
              Create user
            </Button>
          </>
        }
      >
        <div className="grid gap-4 sm:grid-cols-2">
          <Input label="Full name" required value={userForm.full_name} onChange={(event) => setUserForm({ ...userForm, full_name: event.target.value })} />
          <Input label="Email" type="email" required value={userForm.email} onChange={(event) => setUserForm({ ...userForm, email: event.target.value })} />
          <Input label="Temporary password" type="password" required value={userForm.password} onChange={(event) => setUserForm({ ...userForm, password: event.target.value })} hint="Letters and digits, minimum 8" />
          <Select label="Role" value={userForm.role} onChange={(event) => setUserForm({ ...userForm, role: event.target.value as UserRole })}>
            <option value="security_officer">Security officer</option>
            <option value="admin">Administrator</option>
            <option value="resident">Resident</option>
          </Select>
          <Input label="Phone" value={userForm.phone} onChange={(event) => setUserForm({ ...userForm, phone: event.target.value })} className="sm:col-span-2" />
        </div>
      </Modal>

      <Modal
        open={passwordTarget !== null}
        onClose={() => setPasswordTarget(null)}
        title="Reset password"
        description={passwordTarget ? `Set a new password for ${passwordTarget.full_name}` : undefined}
        size="sm"
        footer={
          <>
            <Button variant="outline" onClick={() => setPasswordTarget(null)}>Cancel</Button>
            <Button onClick={() => passwordTarget && resetPasswordMutation.mutate({ id: passwordTarget.id, password: newPassword })} loading={resetPasswordMutation.isPending} disabled={newPassword.length < 8}>
              Reset password
            </Button>
          </>
        }
      >
        <Input label="New password" type="password" value={newPassword} onChange={(event) => setNewPassword(event.target.value)} hint="Minimum 8 characters with a letter and a digit" />
      </Modal>

      <ConfirmDialog
        open={gateToDelete !== null}
        onClose={() => setGateToDelete(null)}
        onConfirm={() => gateToDelete && deleteGateMutation.mutate(gateToDelete)}
        loading={deleteGateMutation.isPending}
        title="Delete gate"
        description={`Delete ${gateToDelete?.name ?? "this gate"} and its cameras? Historical access logs remain.`}
        confirmLabel="Delete gate"
      />

      <ConfirmDialog
        open={cameraToDelete !== null}
        onClose={() => setCameraToDelete(null)}
        onConfirm={() => cameraToDelete && deleteCameraMutation.mutate(cameraToDelete)}
        loading={deleteCameraMutation.isPending}
        title="Delete camera"
        description={`Remove ${cameraToDelete?.name ?? "this camera"} from the pipeline?`}
        confirmLabel="Delete camera"
      />

      <ConfirmDialog
        open={userToDeactivate !== null}
        onClose={() => setUserToDeactivate(null)}
        onConfirm={() => userToDeactivate && deactivateMutation.mutate(userToDeactivate)}
        loading={deactivateMutation.isPending}
        title="Deactivate user"
        description={`${userToDeactivate?.full_name ?? "This user"} will no longer be able to sign in.`}
        confirmLabel="Deactivate"
      />
    </div>
  );
}
