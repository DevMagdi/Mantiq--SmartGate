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
      if (!compound) throw new Error("No compound available");
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
      toast.success(editingResident ? "Resident updated" : "Resident registered");
      setResidentOpen(false);
      setEditingResident(null);
      setResidentForm(EMPTY_RESIDENT);
      await invalidateRegistry();
    },
    onError: (error) => toast.error("Could not save resident", apiErrorMessage(error)),
  });

  const vehicleMutation = useMutation({
    mutationFn: async (): Promise<void> => {
      if (!compound) throw new Error("No compound available");
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
      toast.success(editingVehicle ? "Vehicle updated" : "Vehicle registered");
      setVehicleOpen(false);
      setEditingVehicle(null);
      setVehicleForm(EMPTY_VEHICLE);
      await invalidateRegistry();
    },
    onError: (error) => toast.error("Could not save vehicle", apiErrorMessage(error)),
  });

  const deleteResidentMutation = useMutation({
    mutationFn: (resident: Resident) => deleteResident(resident.id),
    onSuccess: async () => {
      toast.success("Resident removed");
      setResidentToDelete(null);
      await invalidateRegistry();
    },
    onError: (error) => toast.error("Could not remove resident", apiErrorMessage(error)),
  });

  const deleteVehicleMutation = useMutation({
    mutationFn: (vehicle: Vehicle) => deleteVehicle(vehicle.id),
    onSuccess: async () => {
      toast.success("Vehicle removed");
      setVehicleToDelete(null);
      await invalidateRegistry();
    },
    onError: (error) => toast.error("Could not remove vehicle", apiErrorMessage(error)),
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
        eyebrow={isManager ? "Compound registry" : "My household"}
        title={isManager ? "Residents & vehicles" : "My household"}
        subtitle={
          isManager
            ? "Manage unit ownership, resident access rights and the vehicle plates registered for automatic entry."
            : "Your unit, registered vehicles and face enrollment status."
        }
        actions={
          isManager ? (
            <>
              <Button variant="outline" icon="car" onClick={() => openCreateVehicle()}>
                Add vehicle
              </Button>
              <Button icon="plus" onClick={openCreateResident}>
                Add resident
              </Button>
            </>
          ) : (
            <Button variant="outline" icon="visitors" onClick={() => navigate("/visitors")}>
              Invite a visitor
            </Button>
          )
        }
      />

      {!isManager && myProfile.isLoading ? (
        <Card><LoadingBlock label="Loading your household…" /></Card>
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
                  Unit {myProfile.data.unit?.label ?? "—"} · {myProfile.data.role_in_unit} · since {formatDate(myProfile.data.move_in_date)}
                </p>
                <div className="mt-2 flex flex-wrap gap-2">
                  <Badge tone={RESIDENT_STATUS_META[myProfile.data.status].tone} dot>
                    {RESIDENT_STATUS_META[myProfile.data.status].label}
                  </Badge>
                  <Badge tone="neutral">{myProfile.data.vehicle_count} vehicles</Badge>
                  <Badge tone={myProfile.data.face_count > 0 ? "success" : "warning"}>
                    {myProfile.data.face_count > 0 ? "Face enrolled" : "Face not enrolled"}
                  </Badge>
                </div>
              </div>
            </div>
          </Card>
          <Card>
            <CardHeader title="Contact details" icon="users" />
            <dl className="space-y-3 p-5 text-sm">
              <div className="flex justify-between gap-3">
                <dt className="text-ink-500 dark:text-ink-400">Phone</dt>
                <dd className="font-medium">{myProfile.data.phone ?? "—"}</dd>
              </div>
              <div className="flex justify-between gap-3">
                <dt className="text-ink-500 dark:text-ink-400">Email</dt>
                <dd className="truncate font-medium">{myProfile.data.email ?? user?.email ?? "—"}</dd>
              </div>
              <div className="flex justify-between gap-3">
                <dt className="text-ink-500 dark:text-ink-400">National ID</dt>
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
              { key: "residents", label: "Residents", count: residentsQuery.data?.total },
              { key: "vehicles", label: "Vehicles", count: vehiclesQuery.data?.total },
            ]}
            value={tab}
            onChange={(key) => setTab(key)}
          />
          <div className="flex flex-wrap items-center gap-2">
            <SearchInput
              value={search}
              onChange={setSearch}
              placeholder={tab === "residents" ? "Search residents…" : "Search by plate or owner…"}
              className="w-full sm:w-64"
            />
            <Select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)} className="w-36">
              <option value="">All statuses</option>
              {(tab === "residents"
                ? ["active", "inactive", "moved_out"]
                : ["active", "suspended", "inactive"]
              ).map((value) => (
                <option key={value} value={value}>{value.replace("_", " ")}</option>
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
                    <Th>Resident</Th>
                    <Th>Unit</Th>
                    <Th>Relation</Th>
                    <Th>Status</Th>
                    <Th>Vehicles</Th>
                    <Th>Faces</Th>
                    <Th align="right">Actions</Th>
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
                            <p className="text-[10px] text-ink-400">{resident.phone ?? resident.email ?? "No contact"}</p>
                          </div>
                        </div>
                      </Td>
                      <Td className="text-xs">{resident.unit?.label ?? "—"}</Td>
                      <Td className="text-xs capitalize">{resident.role_in_unit}</Td>
                      <Td>
                        <Badge tone={RESIDENT_STATUS_META[resident.status].tone} dot>
                          {RESIDENT_STATUS_META[resident.status].label}
                        </Badge>
                      </Td>
                      <Td className="text-xs">{resident.vehicle_count}</Td>
                      <Td className="text-xs">{resident.face_count}</Td>
                      <Td align="right">
                        <div className="flex justify-end gap-1">
                          <Button variant="ghost" size="icon" onClick={() => openCreateVehicle(resident.id)} aria-label="Add vehicle">
                            <Icon name="car" className="h-4 w-4" />
                          </Button>
                          <Button variant="ghost" size="icon" onClick={() => openEditResident(resident)} aria-label="Edit resident">
                            <Icon name="edit" className="h-4 w-4" />
                          </Button>
                          <Button variant="ghost" size="icon" onClick={() => setResidentToDelete(resident)} aria-label="Delete resident">
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
              title="No residents match the filters"
              description="Register the first resident or adjust the search."
              action={<Button icon="plus" onClick={openCreateResident}>Add resident</Button>}
            />
          )
        ) : (
          (() => {
            const vehicles = isManager ? vehiclesQuery.data?.items ?? [] : myVehicles;
            if (!isManager && vehicles.length === 0) {
              return <EmptyState icon="car" title="No vehicles registered" description="Contact the security office to register a vehicle for your unit." />;
            }
            if (vehicles.length === 0) {
              return (
                <EmptyState
                  icon="car"
                  title="No vehicles registered"
                  description="Register a plate to let the barrier recognise it automatically."
                  action={<Button icon="plus" onClick={() => openCreateVehicle()}>Add vehicle</Button>}
                />
              );
            }
            return (
              <>
                <div className="flex items-center justify-between border-b border-ink-100 px-4 py-3 dark:border-ink-800">
                  <p className="text-sm font-semibold text-ink-900 dark:text-ink-100">
                    {isManager ? "Registered vehicles" : "My vehicles"}
                  </p>
                  <span className="text-[11px] text-ink-400">{vehicles.length} shown</span>
                </div>
                <TableShell>
                  <thead>
                    <tr>
                      <Th>Plate</Th>
                      <Th>Vehicle</Th>
                      <Th>Owner</Th>
                      <Th>Status</Th>
                      <Th>Inside</Th>
                      <Th>Last seen</Th>
                      {isManager ? <Th align="right">Actions</Th> : null}
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
                          <span className="ml-1 text-[10px] text-ink-400">{vehicle.color ?? ""}</span>
                        </Td>
                        <Td className="text-xs">{vehicle.resident?.full_name ?? "Visitor / unassigned"}</Td>
                        <Td>
                          <Badge tone={VEHICLE_STATUS_META[vehicle.status].tone} dot>
                            {VEHICLE_STATUS_META[vehicle.status].label}
                          </Badge>
                        </Td>
                        <Td>
                          {vehicle.is_inside ? (
                            <Badge tone="info">Inside</Badge>
                          ) : (
                            <span className="text-[11px] text-ink-400">Away</span>
                          )}
                        </Td>
                        <Td className="whitespace-nowrap text-[11px] text-ink-500 dark:text-ink-400">
                          {vehicle.last_seen_at ? formatDateTime(vehicle.last_seen_at) : "—"}
                        </Td>
                        {isManager ? (
                          <Td align="right">
                            <div className="flex justify-end gap-1">
                              <Button variant="ghost" size="icon" onClick={() => openEditVehicle(vehicle)} aria-label="Edit vehicle">
                                <Icon name="edit" className="h-4 w-4" />
                              </Button>
                              <Button variant="ghost" size="icon" onClick={() => setVehicleToDelete(vehicle)} aria-label="Delete vehicle">
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
        title={editingResident ? "Edit resident" : "Register a resident"}
        description="Residents inherit the access policy of their unit. Primary residents receive portal accounts."
        size="lg"
        footer={
          <>
            <Button variant="outline" onClick={() => setResidentOpen(false)}>Cancel</Button>
            <Button
              onClick={() => residentMutation.mutate()}
              loading={residentMutation.isPending}
              disabled={!residentForm.full_name.trim() || !residentForm.unit_id}
            >
              {editingResident ? "Save changes" : "Register resident"}
            </Button>
          </>
        }
      >
        <div className="grid gap-4 sm:grid-cols-2">
          <Input
            label="Full name"
            required
            value={residentForm.full_name}
            onChange={(event) => setResidentForm({ ...residentForm, full_name: event.target.value })}
            placeholder="e.g. Mariam Fathy"
          />
          <Input
            label="National ID"
            value={residentForm.national_id}
            onChange={(event) => setResidentForm({ ...residentForm, national_id: event.target.value })}
            placeholder="14-digit national ID"
          />
          <Input
            label="Phone"
            value={residentForm.phone}
            onChange={(event) => setResidentForm({ ...residentForm, phone: event.target.value })}
            placeholder="+20 100 000 0000"
          />
          <Input
            label="Email"
            type="email"
            value={residentForm.email}
            onChange={(event) => setResidentForm({ ...residentForm, email: event.target.value })}
            placeholder="resident@example.com"
          />
          <Select
            label="Unit"
            required
            value={residentForm.unit_id}
            onChange={(event) => setResidentForm({ ...residentForm, unit_id: event.target.value })}
            disabled={Boolean(editingResident)}
            hint={editingResident ? "Use the unit transfer workflow to move a resident." : undefined}
          >
            <option value="">Select a unit…</option>
            {unitOptions.map((unit: Unit) => (
              <option key={unit.id} value={unit.id}>
                {unit.building} · {unit.label} · {unit.status}
              </option>
            ))}
          </Select>
          <Select
            label="Relation to unit"
            value={residentForm.role_in_unit}
            onChange={(event) => setResidentForm({ ...residentForm, role_in_unit: event.target.value as ResidentRelationship })}
          >
            <option value="owner">Owner</option>
            <option value="tenant">Tenant</option>
            <option value="family">Family member</option>
          </Select>
          <Select
            label="Status"
            value={residentForm.status}
            onChange={(event) => setResidentForm({ ...residentForm, status: event.target.value as ResidentStatus })}
          >
            <option value="active">Active</option>
            <option value="inactive">Inactive</option>
            <option value="moved_out">Moved out</option>
          </Select>
          <label className="flex items-center gap-2 self-end pb-2 text-xs font-medium text-ink-600 dark:text-ink-300">
            <input
              type="checkbox"
              checked={residentForm.is_primary}
              onChange={(event) => setResidentForm({ ...residentForm, is_primary: event.target.checked })}
              className="h-4 w-4 rounded border-ink-300 text-brand-600 focus:ring-brand-500"
            />
            Primary resident for the unit
          </label>
          <Textarea
            label="Notes"
            value={residentForm.notes}
            onChange={(event) => setResidentForm({ ...residentForm, notes: event.target.value })}
            className="sm:col-span-2"
            placeholder="Parking allocation, accessibility needs…"
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
                Create a resident portal account
              </label>
              {residentForm.create_account ? (
                <div className="mt-3 grid gap-3 sm:grid-cols-2">
                  <Input label="Account password" type="password" value={residentForm.account_password} onChange={(event) => setResidentForm({ ...residentForm, account_password: event.target.value })} placeholder="Minimum 8 characters" />
                  <p className="self-end pb-2 text-[11px] text-ink-400">The resident signs in with the email above.</p>
                </div>
              ) : null}
            </div>
          ) : null}
        </div>
      </Modal>

      <Modal
        open={vehicleOpen}
        onClose={() => setVehicleOpen(false)}
        title={editingVehicle ? "Edit vehicle" : "Register a vehicle"}
        description="The plate is normalised for OCR matching; the display value stays readable."
        size="lg"
        footer={
          <>
            <Button variant="outline" onClick={() => setVehicleOpen(false)}>Cancel</Button>
            <Button onClick={() => vehicleMutation.mutate()} loading={vehicleMutation.isPending} disabled={vehicleForm.plate_number.trim().length < 3}>
              {editingVehicle ? "Save changes" : "Register vehicle"}
            </Button>
          </>
        }
      >
        <div className="grid gap-4 sm:grid-cols-2">
          <Input
            label="Plate number"
            required
            value={vehicleForm.plate_number}
            onChange={(event) => setVehicleForm({ ...vehicleForm, plate_number: event.target.value.toUpperCase() })}
            placeholder="CAI 4821"
            className="font-mono"
          />
          <Select
            label="Owner"
            value={vehicleForm.resident_id}
            onChange={(event) => setVehicleForm({ ...vehicleForm, resident_id: event.target.value })}
          >
            <option value="">Visitor / unassigned</option>
            {residentOptions.map((resident) => (
              <option key={resident.id} value={resident.id}>{resident.full_name}</option>
            ))}
          </Select>
          <Input label="Make" value={vehicleForm.make} onChange={(event) => setVehicleForm({ ...vehicleForm, make: event.target.value })} placeholder="Toyota" />
          <Input label="Model" value={vehicleForm.model} onChange={(event) => setVehicleForm({ ...vehicleForm, model: event.target.value })} placeholder="Corolla" />
          <Input label="Colour" value={vehicleForm.color} onChange={(event) => setVehicleForm({ ...vehicleForm, color: event.target.value })} placeholder="White" />
          <Input label="Year" type="number" min={1950} max={2100} value={vehicleForm.year} onChange={(event) => setVehicleForm({ ...vehicleForm, year: event.target.value })} placeholder="2022" />
          <Select label="Type" value={vehicleForm.vehicle_type} onChange={(event) => setVehicleForm({ ...vehicleForm, vehicle_type: event.target.value as VehicleType })}>
            <option value="car">Car</option>
            <option value="motorcycle">Motorcycle</option>
            <option value="van">Van</option>
            <option value="truck">Truck</option>
            <option value="other">Other</option>
          </Select>
          <Select label="Status" value={vehicleForm.status} onChange={(event) => setVehicleForm({ ...vehicleForm, status: event.target.value as VehicleStatus })}>
            <option value="active">Active</option>
            <option value="suspended">Suspended</option>
            <option value="inactive">Inactive</option>
          </Select>
          <Input label="Sticker number" value={vehicleForm.sticker_number} onChange={(event) => setVehicleForm({ ...vehicleForm, sticker_number: event.target.value })} placeholder="Optional windshield sticker" />
          <Textarea label="Notes" value={vehicleForm.notes} onChange={(event) => setVehicleForm({ ...vehicleForm, notes: event.target.value })} className="sm:col-span-2" />
        </div>
      </Modal>

      <ConfirmDialog
        open={residentToDelete !== null}
        onClose={() => setResidentToDelete(null)}
        onConfirm={() => residentToDelete && deleteResidentMutation.mutate(residentToDelete)}
        loading={deleteResidentMutation.isPending}
        title="Remove resident"
        description={`Remove ${residentToDelete?.full_name ?? "this resident"} from the compound? Vehicles must be removed first.`}
        confirmLabel="Remove resident"
      />

      <ConfirmDialog
        open={vehicleToDelete !== null}
        onClose={() => setVehicleToDelete(null)}
        onConfirm={() => vehicleToDelete && deleteVehicleMutation.mutate(vehicleToDelete)}
        loading={deleteVehicleMutation.isPending}
        title="Remove vehicle"
        description={`Delete ${vehicleToDelete?.plate_number ?? "this plate"} from the registry? Historical access logs are preserved.`}
        confirmLabel="Remove vehicle"
      />
    </div>
  );
}
