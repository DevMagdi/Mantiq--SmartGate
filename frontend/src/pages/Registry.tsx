import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";

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
  Pagination,
  SearchInput,
  Select,
  TableShell,
  Tabs,
  Td,
  Textarea,
  Th,
} from "@/components/ui";
import { useAuth } from "@/hooks/useAuth";
import { useI18n } from "@/i18n";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { useToast } from "@/hooks/useToast";
import {
  createResident,
  createVehicle,
  deleteResident,
  deleteVehicle,
  getMyResidentProfile,
  listResidents,
  listUnits,
  listVehicles,
  updateResident,
  updateVehicle,
  type ResidentPayload,
  type VehiclePayload,
} from "@/services/registry";
import { listCompounds } from "@/services/admin";
import { apiErrorMessage } from "@/services/api";
import type {
  Resident,
  ResidentRelationship,
  ResidentStatus,
  Unit,
  Vehicle,
  VehicleStatus,
  VehicleType,
} from "@/types/models";
import {
  RESIDENT_STATUS_META,
  VEHICLE_STATUS_META,
} from "@/utils/constants";
import { formatDate, formatDateTime, initials } from "@/utils/format";

type TabKey = "residents" | "vehicles";

interface ResidentForm {
  full_name: string;
  national_id: string;
  phone: string;
  email: string;
  unit_id: string;
  role_in_unit: ResidentRelationship;
  status: ResidentStatus;
  is_primary: boolean;
  notes: string;
  create_account: boolean;
  account_password: string;
}

interface VehicleForm {
  plate_number: string;
  resident_id: string;
  make: string;
  model: string;
  color: string;
  year: string;
  vehicle_type: VehicleType;
  status: VehicleStatus;
  sticker_number: string;
  notes: string;
}

const EMPTY_RESIDENT: ResidentForm = {
  full_name: "",
  national_id: "",
  phone: "",
  email: "",
  unit_id: "",
  role_in_unit: "owner",
  status: "active",
  is_primary: true,
  notes: "",
  create_account: false,
  account_password: "",
};

const EMPTY_VEHICLE: VehicleForm = {
  plate_number: "",
  resident_id: "",
  make: "",
  model: "",
  color: "",
  year: "",
  vehicle_type: "car",
  status: "active",
  sticker_number: "",
  notes: "",
};

export function RegistryPage(): JSX.Element {
  const { t } = useI18n();
  const { user, hasRole } = useAuth();
  const isManager = hasRole("admin", "security_officer");
  const toast = useToast();
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const [tab, setTab] = useState<TabKey>("residents");
  const [search, setSearch] = useState("");
  const debouncedSearch = useDebouncedValue(search);
  const [statusFilter, setStatusFilter] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);

  const [residentOpen, setResidentOpen] = useState(false);
  const [editingResident, setEditingResident] = useState<Resident | null>(null);
  const [residentForm, setResidentForm] = useState<ResidentForm>(EMPTY_RESIDENT);
  const [residentToDelete, setResidentToDelete] = useState<Resident | null>(null);

  const [vehicleOpen, setVehicleOpen] = useState(false);
  const [editingVehicle, setEditingVehicle] = useState<Vehicle | null>(null);
  const [vehicleForm, setVehicleForm] = useState<VehicleForm>(EMPTY_VEHICLE);
  const [vehicleToDelete, setVehicleToDelete] = useState<Vehicle | null>(null);

  useEffect(() => {
    setPage(1);
  }, [debouncedSearch, statusFilter, tab]);

  const compounds = useQuery({
    queryKey: ["compounds"],
    queryFn: listCompounds,
    enabled: isManager,
  });
  const compound = compounds.data?.items[0];
  const units = useQuery({
    queryKey: ["units", compound?.id],
    queryFn: () => listUnits(compound!.id),
    enabled: isManager && Boolean(compound?.id),
  });

  const myProfile = useQuery({
    queryKey: ["my-resident-profile"],
    queryFn: getMyResidentProfile,
    enabled: !isManager,
    retry: false,
  });

  const residentsQuery = useQuery({
    queryKey: ["residents", { debouncedSearch, statusFilter, page, pageSize }],
    queryFn: () =>
      listResidents({
        page,
        page_size: pageSize,
        search: debouncedSearch || undefined,
        status: statusFilter || undefined,
      }),
    enabled: isManager && tab === "residents",
  });

  const vehiclesQuery = useQuery({
    queryKey: ["vehicles", { debouncedSearch, statusFilter, page, pageSize }],
    queryFn: () =>
      listVehicles({
        page,
        page_size: pageSize,
        search: debouncedSearch || undefined,
        status: statusFilter || undefined,
      }),
    enabled: tab === "vehicles" || !isManager,
  });

  const residentDirectory = useQuery({
    queryKey: ["residents", "directory"],
    queryFn: () => listResidents({ page_size: 200, sort_by: "full_name", sort_dir: "asc" }),
    enabled: isManager && vehicleOpen,
  });

  const unitOptions = units.data?.items ?? [];
  const residentOptions = residentDirectory.data?.items ?? residentsQuery.data?.items ?? [];
  const myVehicles = useMemo(() => {
    if (isManager) return [];
    return (vehiclesQuery.data?.items ?? []).filter((vehicle) => vehicle.resident_id === myProfile.data?.id);
  }, [isManager, vehiclesQuery.data, myProfile.data]);

  const invalidateRegistry = async (): Promise<void> => {
    await queryClient.invalidateQueries({ queryKey: ["residents"] });
    await queryClient.invalidateQueries({ queryKey: ["vehicles"] });
    await queryClient.invalidateQueries({ queryKey: ["dashboard"] });
    await queryClient.invalidateQueries({ queryKey: ["my-resident-profile"] });
  };

  const residentMutation = useMutation({
    mutationFn: async (): Promise<void> => {
      if (!compound) throw new Error(t("registry.error.no_compound"));
      const payload: ResidentPayload = {
        compound_id: compound.id,
        unit_id: residentForm.unit_id || unitOptions[0]?.id || "",
        full_name: residentForm.full_name.trim(),
        national_id: residentForm.national_id.trim() || null,
        phone: residentForm.phone.trim() || null,
        email: residentForm.email.trim() || null,
        role_in_unit: residentForm.role_in_unit,
        status: residentForm.status,
        is_primary: residentForm.is_primary,
        notes: residentForm.notes.trim() || null,
        create_account: residentForm.create_account,
        account_password: residentForm.create_account ? residentForm.account_password : null,
      };
      if (editingResident) {
        await updateResident(editingResident.id, {
          full_name: payload.full_name,
          national_id: payload.national_id,
          phone: payload.phone,
          email: payload.email,
          role_in_unit: payload.role_in_unit,
          status: payload.status,
          is_primary: payload.is_primary,
          notes: payload.notes,
        });
      } else {
        await createResident(payload);
      }
    },
    onSuccess: async () => {
      toast.success(editingResident ? t("registry.toast.resident_updated") : t("registry.toast.resident_created"));
      setResidentOpen(false);
      setEditingResident(null);
      setResidentForm(EMPTY_RESIDENT);
      await invalidateRegistry();
    },
    onError: (error) => toast.error(t("registry.toast.resident_error"), apiErrorMessage(error)),
  });

  const vehicleMutation = useMutation({
    mutationFn: async (): Promise<void> => {
      if (!compound) throw new Error(t("registry.error.no_compound"));
      const payload: VehiclePayload = {
        compound_id: compound.id,
        resident_id: vehicleForm.resident_id || null,
        plate_number: vehicleForm.plate_number.trim(),
        make: vehicleForm.make.trim() || null,
        model: vehicleForm.model.trim() || null,
        color: vehicleForm.color.trim() || null,
        year: vehicleForm.year ? Number(vehicleForm.year) : null,
        vehicle_type: vehicleForm.vehicle_type,
        status: vehicleForm.status,
        sticker_number: vehicleForm.sticker_number.trim() || null,
        notes: vehicleForm.notes.trim() || null,
      };
      if (editingVehicle) {
        await updateVehicle(editingVehicle.id, {
          resident_id: payload.resident_id,
          plate_number: payload.plate_number,
          make: payload.make,
          model: payload.model,
          color: payload.color,
          year: payload.year,
          vehicle_type: payload.vehicle_type,
          status: payload.status,
          sticker_number: payload.sticker_number,
          notes: payload.notes,
        });
      } else {
        await createVehicle(payload);
      }
    },
    onSuccess: async () => {
      toast.success(editingVehicle ? t("registry.toast.vehicle_updated") : t("registry.toast.vehicle_created"));
      setVehicleOpen(false);
      setEditingVehicle(null);
      setVehicleForm(EMPTY_VEHICLE);
      await invalidateRegistry();
    },
    onError: (error) => toast.error(t("registry.toast.vehicle_error"), apiErrorMessage(error)),
  });

  const deleteResidentMutation = useMutation({
    mutationFn: (resident: Resident) => deleteResident(resident.id),
    onSuccess: async () => {
      toast.success(t("registry.toast.resident_removed"));
      setResidentToDelete(null);
      await invalidateRegistry();
    },
    onError: (error) => toast.error(t("registry.toast.resident_remove_error"), apiErrorMessage(error)),
  });

  const deleteVehicleMutation = useMutation({
    mutationFn: (vehicle: Vehicle) => deleteVehicle(vehicle.id),
    onSuccess: async () => {
      toast.success(t("registry.toast.vehicle_removed"));
      setVehicleToDelete(null);
      await invalidateRegistry();
    },
    onError: (error) => toast.error(t("registry.toast.vehicle_remove_error"), apiErrorMessage(error)),
  });

  const openCreateResident = (): void => {
    setEditingResident(null);
    setResidentForm({ ...EMPTY_RESIDENT, unit_id: unitOptions[0]?.id ?? "" });
    setResidentOpen(true);
  };

  const openEditResident = (resident: Resident): void => {
    setEditingResident(resident);
    setResidentForm({
      full_name: resident.full_name,
      national_id: resident.national_id ?? "",
      phone: resident.phone ?? "",
      email: resident.email ?? "",
      unit_id: resident.unit_id,
      role_in_unit: resident.role_in_unit,
      status: resident.status,
      is_primary: resident.is_primary,
      notes: resident.notes ?? "",
      create_account: false,
      account_password: "",
    });
    setResidentOpen(true);
  };

  const openCreateVehicle = (residentId?: string): void => {
    setEditingVehicle(null);
    setVehicleForm({ ...EMPTY_VEHICLE, resident_id: residentId ?? "" });
    setVehicleOpen(true);
  };

  const openEditVehicle = (vehicle: Vehicle): void => {
    setEditingVehicle(vehicle);
    setVehicleForm({
      plate_number: vehicle.plate_number,
      resident_id: vehicle.resident_id ?? "",
      make: vehicle.make ?? "",
      model: vehicle.model ?? "",
      color: vehicle.color ?? "",
      year: vehicle.year ? String(vehicle.year) : "",
      vehicle_type: vehicle.vehicle_type,
      status: vehicle.status,
      sticker_number: vehicle.sticker_number ?? "",
      notes: vehicle.notes ?? "",
    });
    setVehicleOpen(true);
  };

  const activeQuery = tab === "residents" ? residentsQuery : vehiclesQuery;

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow={isManager ? t("registry.eyebrow.manager") : t("registry.eyebrow.resident")}
        title={isManager ? t("registry.title.manager") : t("registry.title.resident")}
        subtitle={isManager ? t("registry.subtitle.manager") : t("registry.subtitle.resident")}
        actions={
          isManager ? (
            <>
              <Button variant="outline" icon="car" onClick={() => openCreateVehicle()}>
                {t("registry.add_vehicle")}
              </Button>
              <Button icon="plus" onClick={openCreateResident}>
                {t("registry.add_resident")}
              </Button>
            </>
          ) : (
            <Button variant="outline" icon="visitors" onClick={() => navigate("/visitors")}>
              {t("registry.invite")}
            </Button>
          )
        }
      />

      {!isManager && myProfile.isLoading ? (
        <Card><LoadingBlock label={t("registry.loading_household")} /></Card>
      ) : null}

      {!isManager && myProfile.data ? (
        <div className="grid gap-4 lg:grid-cols-3">
          <Card className="lg:col-span-2">
            <div className="flex flex-wrap items-center gap-4 p-5">
              <span className="grid h-14 w-14 place-items-center rounded-2xl bg-gradient-to-br from-brand-500 to-brand-700 text-lg font-bold text-white">
                {initials(myProfile.data.full_name)}
              </span>
              <div className="min-w-0 flex-1">
                <p className="text-lg font-bold">{myProfile.data.full_name}</p>
                <p className="text-xs text-ink-500 dark:text-ink-400">
                  {t("registry.unit_line", {
                    unit: myProfile.data.unit?.label ?? "—",
                    role: t(`relation.${myProfile.data.role_in_unit}`),
                    date: formatDate(myProfile.data.move_in_date),
                  })}
                </p>
                <div className="mt-2 flex flex-wrap gap-2">
                  <Badge tone={RESIDENT_STATUS_META[myProfile.data.status].tone} dot>
                    {t(`status.${myProfile.data.status}`)}
                  </Badge>
                  <Badge tone="neutral">{t("registry.vehicles_count", { count: myProfile.data.vehicle_count })}</Badge>
                  <Badge tone={myProfile.data.face_count > 0 ? "success" : "warning"}>
                    {myProfile.data.face_count > 0 ? t("registry.face_enrolled") : t("registry.face_missing")}
                  </Badge>
                </div>
              </div>
            </div>
          </Card>
          <Card>
            <CardHeader title={t("registry.contact")} icon="users" />
            <dl className="space-y-3 p-5 text-sm">
              <div className="flex justify-between gap-3">
                <dt className="text-ink-500 dark:text-ink-400">{t("common.phone")}</dt>
                <dd className="font-medium">{myProfile.data.phone ?? "—"}</dd>
              </div>
              <div className="flex justify-between gap-3">
                <dt className="text-ink-500 dark:text-ink-400">{t("common.email")}</dt>
                <dd className="truncate font-medium">{myProfile.data.email ?? user?.email ?? "—"}</dd>
              </div>
              <div className="flex justify-between gap-3">
                <dt className="text-ink-500 dark:text-ink-400">{t("registry.national_id")}</dt>
                <dd className="font-mono text-xs font-medium">{myProfile.data.national_id ?? "—"}</dd>
              </div>
            </dl>
          </Card>
        </div>
      ) : null}

      {isManager ? (
        <div className="flex flex-wrap items-center justify-between gap-3">
          <Tabs
            tabs={[
              { key: "residents", label: t("registry.tab.residents"), count: residentsQuery.data?.total },
              { key: "vehicles", label: t("registry.tab.vehicles"), count: vehiclesQuery.data?.total },
            ]}
            value={tab}
            onChange={(key) => setTab(key)}
          />
          <div className="flex flex-wrap items-center gap-2">
            <SearchInput
              value={search}
              onChange={setSearch}
              placeholder={tab === "residents" ? t("registry.search.residents") : t("registry.search.vehicles")}
              className="w-full sm:w-64"
            />
            <Select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)} className="w-36">
              <option value="">{t("common.all_statuses")}</option>
              {(tab === "residents"
                ? ["active", "inactive", "moved_out"]
                : ["active", "suspended", "inactive"]
              ).map((value) => (
                <option key={value} value={value}>{t(`status.${value}`)}</option>
              ))}
            </Select>
          </div>
        </div>
      ) : null}

      <Card>
        {activeQuery.isLoading ? (
          <LoadingBlock />
        ) : tab === "residents" && isManager ? (
          residentsQuery.data && residentsQuery.data.items.length > 0 ? (
            <>
              <TableShell>
                <thead>
                  <tr>
                    <Th>{t("registry.table.resident")}</Th>
                    <Th>{t("common.unit")}</Th>
                    <Th>{t("registry.table.relation")}</Th>
                    <Th>{t("common.status")}</Th>
                    <Th>{t("registry.table.vehicles")}</Th>
                    <Th>{t("registry.table.faces")}</Th>
                    <Th align="right">{t("common.actions")}</Th>
                  </tr>
                </thead>
                <tbody>
                  {residentsQuery.data.items.map((resident) => (
                    <tr key={resident.id} className="transition hover:bg-ink-50/70 dark:hover:bg-ink-800/30">
                      <Td>
                        <div className="flex items-center gap-3">
                          <span className="grid h-8 w-8 place-items-center rounded-full bg-brand-50 text-[10px] font-bold text-brand-700 dark:bg-brand-500/10 dark:text-brand-300">
                            {initials(resident.full_name)}
                          </span>
                          <div>
                            <p className="text-sm font-semibold text-ink-900 dark:text-ink-100">{resident.full_name}</p>
                            <p className="text-[10px] text-ink-400">{resident.phone ?? resident.email ?? t("common.no_contact")}</p>
                          </div>
                        </div>
                      </Td>
                      <Td className="text-xs">{resident.unit?.label ?? "—"}</Td>
                      <Td className="text-xs capitalize">{t(`relation.${resident.role_in_unit}`)}</Td>
                      <Td>
                        <Badge tone={RESIDENT_STATUS_META[resident.status].tone} dot>
                          {t(`status.${resident.status}`)}
                        </Badge>
                      </Td>
                      <Td className="text-xs">{resident.vehicle_count}</Td>
                      <Td className="text-xs">{resident.face_count}</Td>
                      <Td align="right">
                        <div className="flex justify-end gap-1">
                          <Button variant="ghost" size="icon" onClick={() => openCreateVehicle(resident.id)} aria-label={t("registry.add_vehicle")}>
                            <Icon name="car" className="h-4 w-4" />
                          </Button>
                          <Button variant="ghost" size="icon" onClick={() => openEditResident(resident)} aria-label={t("registry.action.edit_resident")}>
                            <Icon name="edit" className="h-4 w-4" />
                          </Button>
                          <Button variant="ghost" size="icon" onClick={() => setResidentToDelete(resident)} aria-label={t("registry.action.delete_resident")}>
                            <Icon name="trash" className="h-4 w-4 text-rose-500" />
                          </Button>
                        </div>
                      </Td>
                    </tr>
                  ))}
                </tbody>
              </TableShell>
              <Pagination
                page={residentsQuery.data.page}
                pages={residentsQuery.data.pages}
                total={residentsQuery.data.total}
                pageSize={pageSize}
                onPageChange={setPage}
                onPageSizeChange={(size) => { setPageSize(size); setPage(1); }}
              />
            </>
          ) : (
            <EmptyState
              icon="users"
              title={t("registry.residents.empty_title")}
              description={t("registry.residents.empty_desc")}
              action={<Button icon="plus" onClick={openCreateResident}>{t("registry.add_resident")}</Button>}
            />
          )
        ) : (
          (() => {
            const vehicles = isManager ? vehiclesQuery.data?.items ?? [] : myVehicles;
            if (!isManager && vehicles.length === 0) {
              return <EmptyState icon="car" title={t("registry.vehicles.empty_title")} description={t("registry.vehicles.empty_desc_resident")} />;
            }
            if (vehicles.length === 0) {
              return (
                <EmptyState
                  icon="car"
                  title={t("registry.vehicles.empty_title")}
                  description={t("registry.vehicles.empty_desc_manager")}
                  action={<Button icon="plus" onClick={() => openCreateVehicle()}>{t("registry.add_vehicle")}</Button>}
                />
              );
            }
            return (
              <>
                <div className="flex items-center justify-between border-b border-ink-100 px-4 py-3 dark:border-ink-800">
                  <p className="text-sm font-semibold text-ink-900 dark:text-ink-100">
                    {isManager ? t("registry.vehicles.registered") : t("registry.vehicles.mine")}
                  </p>
                  <span className="text-[11px] text-ink-400">{t("registry.vehicles.shown", { count: vehicles.length })}</span>
                </div>
                <TableShell>
                  <thead>
                    <tr>
                      <Th>{t("common.plate")}</Th>
                      <Th>{t("registry.table.vehicle")}</Th>
                      <Th>{t("registry.table.owner")}</Th>
                      <Th>{t("common.status")}</Th>
                      <Th>{t("registry.table.inside")}</Th>
                      <Th>{t("registry.table.last_seen")}</Th>
                      {isManager ? <Th align="right">{t("common.actions")}</Th> : null}
                    </tr>
                  </thead>
                  <tbody>
                    {vehicles.map((vehicle) => (
                      <tr key={vehicle.id} className="transition hover:bg-ink-50/70 dark:hover:bg-ink-800/30">
                        <Td>
                          <span className="inline-flex rounded-md border border-ink-300 bg-white px-2 py-0.5 font-mono text-xs font-bold tracking-wider text-ink-900 dark:border-ink-600 dark:bg-ink-950 dark:text-ink-100">
                            {vehicle.plate_number}
                          </span>
                        </Td>
                        <Td className="text-xs">
                          {[vehicle.make, vehicle.model].filter(Boolean).join(" ") || "—"}
                          <span className="ms-1 text-[10px] text-ink-400">{vehicle.color ?? ""}</span>
                        </Td>
                        <Td className="text-xs">{vehicle.resident?.full_name ?? t("registry.vehicle.unassigned")}</Td>
                        <Td>
                          <Badge tone={VEHICLE_STATUS_META[vehicle.status].tone} dot>
                            {t(`status.${vehicle.status}`)}
                          </Badge>
                        </Td>
                        <Td>
                          {vehicle.is_inside ? (
                            <Badge tone="info">{t("registry.table.inside")}</Badge>
                          ) : (
                            <span className="text-[11px] text-ink-400">{t("registry.badge.away")}</span>
                          )}
                        </Td>
                        <Td className="whitespace-nowrap text-[11px] text-ink-500 dark:text-ink-400">
                          {vehicle.last_seen_at ? formatDateTime(vehicle.last_seen_at) : "—"}
                        </Td>
                        {isManager ? (
                          <Td align="right">
                            <div className="flex justify-end gap-1">
                              <Button variant="ghost" size="icon" onClick={() => openEditVehicle(vehicle)} aria-label={t("registry.action.edit_vehicle")}>
                                <Icon name="edit" className="h-4 w-4" />
                              </Button>
                              <Button variant="ghost" size="icon" onClick={() => setVehicleToDelete(vehicle)} aria-label={t("registry.action.delete_vehicle")}>
                                <Icon name="trash" className="h-4 w-4 text-rose-500" />
                              </Button>
                            </div>
                          </Td>
                        ) : null}
                      </tr>
                    ))}
                  </tbody>
                </TableShell>
                {isManager && vehiclesQuery.data ? (
                  <Pagination
                    page={vehiclesQuery.data.page}
                    pages={vehiclesQuery.data.pages}
                    total={vehiclesQuery.data.total}
                    pageSize={pageSize}
                    onPageChange={setPage}
                    onPageSizeChange={(size) => { setPageSize(size); setPage(1); }}
                  />
                ) : null}
              </>
            );
          })()
        )}
      </Card>

      <Modal
        open={residentOpen}
        onClose={() => setResidentOpen(false)}
        title={editingResident ? t("registry.modal.edit_resident") : t("registry.modal.create_resident")}
        description={t("registry.modal.resident_desc")}
        size="lg"
        footer={
          <>
            <Button variant="outline" onClick={() => setResidentOpen(false)}>{t("common.cancel")}</Button>
            <Button
              onClick={() => residentMutation.mutate()}
              loading={residentMutation.isPending}
              disabled={!residentForm.full_name.trim() || !residentForm.unit_id}
            >
              {editingResident ? t("common.save_changes") : t("registry.register_resident")}
            </Button>
          </>
        }
      >
        <div className="grid gap-4 sm:grid-cols-2">
          <Input
            label={t("settings.user.full_name")}
            required
            value={residentForm.full_name}
            onChange={(event) => setResidentForm({ ...residentForm, full_name: event.target.value })}
            placeholder={t("registry.form.name_placeholder")}
          />
          <Input
            label={t("registry.national_id")}
            value={residentForm.national_id}
            onChange={(event) => setResidentForm({ ...residentForm, national_id: event.target.value })}
            placeholder={t("registry.form.national_id_placeholder")}
          />
          <Input
            label={t("common.phone")}
            value={residentForm.phone}
            onChange={(event) => setResidentForm({ ...residentForm, phone: event.target.value })}
            placeholder="+20 100 000 0000"
          />
          <Input
            label={t("common.email")}
            type="email"
            value={residentForm.email}
            onChange={(event) => setResidentForm({ ...residentForm, email: event.target.value })}
            placeholder="resident@example.com"
          />
          <Select
            label={t("common.unit")}
            required
            value={residentForm.unit_id}
            onChange={(event) => setResidentForm({ ...residentForm, unit_id: event.target.value })}
            disabled={Boolean(editingResident)}
            hint={editingResident ? t("registry.form.unit_locked_hint") : undefined}
          >
            <option value="">{t("registry.form.select_unit")}</option>
            {unitOptions.map((unit: Unit) => (
              <option key={unit.id} value={unit.id}>
                {unit.building} · {unit.label} · {unit.status}
              </option>
            ))}
          </Select>
          <Select
            label={t("registry.form.relation")}
            value={residentForm.role_in_unit}
            onChange={(event) => setResidentForm({ ...residentForm, role_in_unit: event.target.value as ResidentRelationship })}
          >
            <option value="owner">{t("relation.owner")}</option>
            <option value="tenant">{t("relation.tenant")}</option>
            <option value="family">{t("relation.family")}</option>
          </Select>
          <Select
            label={t("common.status")}
            value={residentForm.status}
            onChange={(event) => setResidentForm({ ...residentForm, status: event.target.value as ResidentStatus })}
          >
            <option value="active">{t("status.active")}</option>
            <option value="inactive">{t("status.inactive")}</option>
            <option value="moved_out">{t("status.moved_out")}</option>
          </Select>
          <label className="flex items-center gap-2 self-end pb-2 text-xs font-medium text-ink-600 dark:text-ink-300">
            <input
              type="checkbox"
              checked={residentForm.is_primary}
              onChange={(event) => setResidentForm({ ...residentForm, is_primary: event.target.checked })}
              className="h-4 w-4 rounded border-ink-300 text-brand-600 focus:ring-brand-500"
            />
            {t("registry.form.primary")}
          </label>
          <Textarea
            label={t("common.notes")}
            value={residentForm.notes}
            onChange={(event) => setResidentForm({ ...residentForm, notes: event.target.value })}
            className="sm:col-span-2"
            placeholder={t("registry.form.notes_placeholder")}
          />
          {!editingResident ? (
            <div className="sm:col-span-2 rounded-xl border border-ink-200 p-3 dark:border-ink-700">
              <label className="flex items-center gap-2 text-xs font-semibold text-ink-700 dark:text-ink-200">
                <input
                  type="checkbox"
                  checked={residentForm.create_account}
                  onChange={(event) => setResidentForm({ ...residentForm, create_account: event.target.checked })}
                  className="h-4 w-4 rounded border-ink-300 text-brand-600 focus:ring-brand-500"
                />
                {t("registry.form.create_account")}
              </label>
              {residentForm.create_account ? (
                <div className="mt-3 grid gap-3 sm:grid-cols-2">
                  <Input label={t("registry.form.account_password")} type="password" value={residentForm.account_password} onChange={(event) => setResidentForm({ ...residentForm, account_password: event.target.value })} placeholder={t("registry.form.account_password_placeholder")} />
                  <p className="self-end pb-2 text-[11px] text-ink-400">{t("registry.form.account_hint")}</p>
                </div>
              ) : null}
            </div>
          ) : null}
        </div>
      </Modal>

      <Modal
        open={vehicleOpen}
        onClose={() => setVehicleOpen(false)}
        title={editingVehicle ? t("registry.modal.edit_vehicle") : t("registry.modal.create_vehicle")}
        description={t("registry.modal.vehicle_desc")}
        size="lg"
        footer={
          <>
            <Button variant="outline" onClick={() => setVehicleOpen(false)}>{t("common.cancel")}</Button>
            <Button onClick={() => vehicleMutation.mutate()} loading={vehicleMutation.isPending} disabled={vehicleForm.plate_number.trim().length < 3}>
              {editingVehicle ? t("common.save_changes") : t("registry.register_vehicle")}
            </Button>
          </>
        }
      >
        <div className="grid gap-4 sm:grid-cols-2">
          <Input
            label={t("security.form.plate")}
            required
            value={vehicleForm.plate_number}
            onChange={(event) => setVehicleForm({ ...vehicleForm, plate_number: event.target.value.toUpperCase() })}
            placeholder="CAI 4821"
            className="font-mono"
          />
          <Select
            label={t("registry.table.owner")}
            value={vehicleForm.resident_id}
            onChange={(event) => setVehicleForm({ ...vehicleForm, resident_id: event.target.value })}
          >
            <option value="">{t("registry.form.owner_unassigned")}</option>
            {residentOptions.map((resident) => (
              <option key={resident.id} value={resident.id}>{resident.full_name}</option>
            ))}
          </Select>
          <Input label={t("registry.form.make")} value={vehicleForm.make} onChange={(event) => setVehicleForm({ ...vehicleForm, make: event.target.value })} placeholder="Toyota" />
          <Input label={t("registry.form.model")} value={vehicleForm.model} onChange={(event) => setVehicleForm({ ...vehicleForm, model: event.target.value })} placeholder="Corolla" />
          <Input label={t("registry.form.colour")} value={vehicleForm.color} onChange={(event) => setVehicleForm({ ...vehicleForm, color: event.target.value })} placeholder={t("registry.form.colour_placeholder")} />
          <Input label={t("registry.form.year")} type="number" min={1950} max={2100} value={vehicleForm.year} onChange={(event) => setVehicleForm({ ...vehicleForm, year: event.target.value })} placeholder="2022" />
          <Select label={t("common.type")} value={vehicleForm.vehicle_type} onChange={(event) => setVehicleForm({ ...vehicleForm, vehicle_type: event.target.value as VehicleType })}>
            <option value="car">{t("registry.type.car")}</option>
            <option value="motorcycle">{t("registry.type.motorcycle")}</option>
            <option value="van">{t("registry.type.van")}</option>
            <option value="truck">{t("registry.type.truck")}</option>
            <option value="other">{t("registry.type.other")}</option>
          </Select>
          <Select label={t("common.status")} value={vehicleForm.status} onChange={(event) => setVehicleForm({ ...vehicleForm, status: event.target.value as VehicleStatus })}>
            <option value="active">{t("status.active")}</option>
            <option value="suspended">{t("status.suspended")}</option>
            <option value="inactive">{t("status.inactive")}</option>
          </Select>
          <Input label={t("registry.form.sticker")} value={vehicleForm.sticker_number} onChange={(event) => setVehicleForm({ ...vehicleForm, sticker_number: event.target.value })} placeholder={t("registry.form.sticker_placeholder")} />
          <Textarea label={t("common.notes")} value={vehicleForm.notes} onChange={(event) => setVehicleForm({ ...vehicleForm, notes: event.target.value })} className="sm:col-span-2" />
        </div>
      </Modal>

      <ConfirmDialog
        open={residentToDelete !== null}
        onClose={() => setResidentToDelete(null)}
        onConfirm={() => residentToDelete && deleteResidentMutation.mutate(residentToDelete)}
        loading={deleteResidentMutation.isPending}
        title={t("registry.delete_resident.title")}
        description={t("registry.delete_resident.desc", { name: residentToDelete?.full_name ?? t("common.resident") })}
        confirmLabel={t("registry.delete_resident.confirm")}
      />

      <ConfirmDialog
        open={vehicleToDelete !== null}
        onClose={() => setVehicleToDelete(null)}
        onConfirm={() => vehicleToDelete && deleteVehicleMutation.mutate(vehicleToDelete)}
        loading={deleteVehicleMutation.isPending}
        title={t("registry.delete_vehicle.title")}
        description={t("registry.delete_vehicle.desc", { plate: vehicleToDelete?.plate_number ?? t("common.plate") })}
        confirmLabel={t("registry.delete_vehicle.confirm")}
      />
    </div>
  );
}
