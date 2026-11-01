import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Icon } from "@/components/Icon";
import { PageHeader } from "@/components/PageHeader";
import {
  Badge,
  Button,
  Card,
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
import { listCompounds } from "@/services/admin";
import { getMyResidentProfile, listUnits } from "@/services/registry";
import {
  createPermit,
  createVisitor,
  listPermits,
  listVisitors,
  revokePermit,
  visitorAction,
  type PermitPayload,
  type VisitorPayload,
} from "@/services/visitors";
import { apiErrorMessage } from "@/services/api";
import type { Permit, Visitor, VisitorStatus } from "@/types/models";
import { PERMIT_STATUS_META, VISITOR_STATUS_META } from "@/utils/constants";
import { formatDateTime, plusHours, toDateTimeLocal } from "@/utils/format";

type TabKey = "visitors" | "permits";
type VisitorAction = "approve" | "reject" | "check-in" | "check-out";

interface VisitorForm {
  full_name: string;
  phone: string;
  email: string;
  company: string;
  purpose: string;
  host_unit_id: string;
  expected_arrival: string;
  notes: string;
}

interface PermitForm {
  visitor_id: string;
  host_unit_id: string;
  start_at: string;
  end_at: string;
  permit_type: string;
  max_entries: string;
  vehicle_plate: string;
  notes: string;
}

const EMPTY_VISITOR: VisitorForm = {
  full_name: "",
  phone: "",
  email: "",
  company: "",
  purpose: "",
  host_unit_id: "",
  expected_arrival: toDateTimeLocal(new Date(Date.now() + 3_600_000)),
  notes: "",
};

const EMPTY_PERMIT: PermitForm = {
  visitor_id: "",
  host_unit_id: "",
  start_at: toDateTimeLocal(),
  end_at: plusHours(4),
  permit_type: "visitor",
  max_entries: "1",
  vehicle_plate: "",
  notes: "",
};

export function VisitorsPage(): JSX.Element {
  const { hasRole } = useAuth();
  const isManager = hasRole("admin", "security_officer");
  const toast = useToast();
  const queryClient = useQueryClient();

  const [tab, setTab] = useState<TabKey>("visitors");
  const [search, setSearch] = useState("");
  const debouncedSearch = useDebouncedValue(search);
  const [statusFilter, setStatusFilter] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);

  const [visitorOpen, setVisitorOpen] = useState(false);
  const [visitorForm, setVisitorForm] = useState<VisitorForm>(EMPTY_VISITOR);
  const [permitOpen, setPermitOpen] = useState(false);
  const [permitForm, setPermitForm] = useState<PermitForm>(EMPTY_PERMIT);
  const [permitToRevoke, setPermitToRevoke] = useState<Permit | null>(null);
  const [revokeReason, setRevokeReason] = useState("Permit no longer required");
  const [visitorToReject, setVisitorToReject] = useState<Visitor | null>(null);

  useEffect(() => {
    setPage(1);
  }, [debouncedSearch, statusFilter, tab]);

  const compounds = useQuery({ queryKey: ["compounds"], queryFn: listCompounds, enabled: isManager });
  const compound = compounds.data?.items[0];
  const myProfile = useQuery({ queryKey: ["my-resident-profile"], queryFn: getMyResidentProfile, enabled: !isManager, retry: false });
  const units = useQuery({
    queryKey: ["units", compound?.id],
    queryFn: () => listUnits(compound!.id),
    enabled: isManager && Boolean(compound?.id),
  });

  const visitorsQuery = useQuery({
    queryKey: ["visitors", { debouncedSearch, statusFilter, page, pageSize }],
    queryFn: () =>
      listVisitors({
        page,
        page_size: pageSize,
        search: debouncedSearch || undefined,
        status: tab === "visitors" && statusFilter ? (statusFilter as VisitorStatus) : undefined,
      }),
    enabled: tab === "visitors",
  });

  const permitsQuery = useQuery({
    queryKey: ["permits", { debouncedSearch, statusFilter, page, pageSize }],
    queryFn: () =>
      listPermits({
        page,
        page_size: pageSize,
        search: debouncedSearch || undefined,
        status: tab === "permits" && statusFilter ? statusFilter : undefined,
      }),
    enabled: tab === "permits",
  });

  const visitorDirectory = useQuery({
    queryKey: ["visitors", "directory"],
    queryFn: () => listVisitors({ page_size: 200, sort_by: "created_at", sort_dir: "desc" }),
    enabled: isManager && permitOpen,
  });

  const unitOptions = units.data?.items ?? (myProfile.data ? [{ id: myProfile.data.unit_id, label: myProfile.data.unit?.label ?? "My unit", building: myProfile.data.unit?.building ?? "" }] : []);
  const defaultUnitId = myProfile.data?.unit_id ?? unitOptions[0]?.id ?? "";

  const invalidate = async (): Promise<void> => {
    await queryClient.invalidateQueries({ queryKey: ["visitors"] });
    await queryClient.invalidateQueries({ queryKey: ["permits"] });
    await queryClient.invalidateQueries({ queryKey: ["dashboard"] });
  };

  const createVisitorMutation = useMutation({
    mutationFn: async (): Promise<void> => {
      if (!compound && isManager) throw new Error("No compound available");
      const payload: VisitorPayload = {
        compound_id: compound?.id ?? myProfile.data?.compound_id ?? "",
        host_unit_id: visitorForm.host_unit_id || defaultUnitId,
        full_name: visitorForm.full_name.trim(),
        phone: visitorForm.phone.trim() || null,
        email: visitorForm.email.trim() || null,
        company: visitorForm.company.trim() || null,
        purpose: visitorForm.purpose.trim() || null,
        expected_arrival: visitorForm.expected_arrival ? new Date(visitorForm.expected_arrival).toISOString() : null,
        notes: visitorForm.notes.trim() || null,
      };
      await createVisitor(payload);
    },
    onSuccess: async () => {
      toast.success("Visitor request created", isManager ? "Approve it and issue a permit when ready." : "Security will review the request.");
      setVisitorOpen(false);
      setVisitorForm(EMPTY_VISITOR);
      await invalidate();
    },
    onError: (error) => toast.error("Could not create visitor", apiErrorMessage(error)),
  });

  const actionMutation = useMutation({
    mutationFn: ({ visitorId, action }: { visitorId: string; action: VisitorAction }) => visitorAction(visitorId, action),
    onSuccess: async (_visitor, variables) => {
      toast.success(`Visitor ${variables.action.replace("-", " ")}d`);
      setVisitorToReject(null);
      await invalidate();
    },
    onError: (error) => toast.error("Visitor action failed", apiErrorMessage(error)),
  });

  const permitMutation = useMutation({
    mutationFn: async (): Promise<void> => {
      const visitor = visitorDirectory.data?.items.find((item) => item.id === permitForm.visitor_id);
      const payload: PermitPayload = {
        visitor_id: permitForm.visitor_id,
        host_unit_id: permitForm.host_unit_id || visitor?.host_unit_id || defaultUnitId,
        start_at: new Date(permitForm.start_at).toISOString(),
        end_at: new Date(permitForm.end_at).toISOString(),
        permit_type: permitForm.permit_type as PermitPayload["permit_type"],
        max_entries: Number(permitForm.max_entries) || 1,
        vehicle_plate: permitForm.vehicle_plate.trim() || null,
        notes: permitForm.notes.trim() || null,
      };
      await createPermit(payload);
    },
    onSuccess: async () => {
      toast.success("Permit issued", "The plate can now pass through the gate while the permit is valid.");
      setPermitOpen(false);
      setPermitForm(EMPTY_PERMIT);
      await invalidate();
    },
    onError: (error) => toast.error("Could not issue permit", apiErrorMessage(error)),
  });

  const revokeMutation = useMutation({
    mutationFn: ({ permitId, reason }: { permitId: string; reason: string }) => revokePermit(permitId, reason),
    onSuccess: async () => {
      toast.success("Permit revoked");
      setPermitToRevoke(null);
      await invalidate();
    },
    onError: (error) => toast.error("Could not revoke permit", apiErrorMessage(error)),
  });

  const openVisitorModal = (): void => {
    setVisitorForm({ ...EMPTY_VISITOR, host_unit_id: defaultUnitId });
    setVisitorOpen(true);
  };

  const openPermitModal = (visitor?: Visitor): void => {
    setPermitForm({
      ...EMPTY_PERMIT,
      visitor_id: visitor?.id ?? "",
      host_unit_id: visitor?.host_unit_id ?? defaultUnitId,
    });
    setPermitOpen(true);
  };

  const activeQuery = tab === "visitors" ? visitorsQuery : permitsQuery;
  const totalVisitors = visitorsQuery.data?.total;

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow={isManager ? "Access scheduling" : "My visitors"}
        title={isManager ? "Visitors & permits" : "My visitors & permits"}
        subtitle="Temporary permits with a start, an expiry and an entry budget — enforced automatically by the gate controller."
        actions={
          <>
            {isManager ? (
              <Button variant="outline" icon="key" onClick={() => openPermitModal()}>
                Issue permit
              </Button>
            ) : null}
            <Button icon="plus" onClick={openVisitorModal}>
              {isManager ? "Register visitor" : "Request visitor"}
            </Button>
          </>
        }
      />

      <div className="flex flex-wrap items-center justify-between gap-3">
        <Tabs
          tabs={[
            { key: "visitors", label: "Visitors", count: totalVisitors },
            { key: "permits", label: "Permits", count: permitsQuery.data?.total },
          ]}
          value={tab}
          onChange={(key) => { setTab(key); setStatusFilter(""); }}
        />
        <div className="flex flex-wrap items-center gap-2">
          <SearchInput value={search} onChange={setSearch} placeholder={tab === "visitors" ? "Search visitors…" : "Search permits or plates…"} className="w-full sm:w-64" />
          <Select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)} className="w-40">
            <option value="">All statuses</option>
            {tab === "visitors"
              ? ["pending", "approved", "checked_in", "checked_out", "rejected", "expired"].map((value) => (
                  <option key={value} value={value}>{value.replace("_", " ")}</option>
                ))
              : ["pending", "active", "expired", "revoked"].map((value) => (
                  <option key={value} value={value}>{value}</option>
                ))}
          </Select>
        </div>
      </div>

      <Card>
        {activeQuery.isLoading ? (
          <LoadingBlock />
        ) : tab === "visitors" ? (
          (visitorsQuery.data?.items ?? []).length === 0 ? (
            <EmptyState
              icon="visitors"
              title="No visitors yet"
              description={isManager ? "Register a visitor or wait for a resident request." : "Request a visitor and security will approve it."}
              action={<Button icon="plus" onClick={openVisitorModal}>Register visitor</Button>}
            />
          ) : (
            <>
              <TableShell>
                <thead>
                  <tr>
                    <Th>Visitor</Th>
                    <Th>Host unit</Th>
                    <Th>Purpose</Th>
                    <Th>Expected</Th>
                    <Th>Status</Th>
                    <Th align="right">Actions</Th>
                  </tr>
                </thead>
                <tbody>
                  {(visitorsQuery.data?.items ?? []).map((visitor) => {
                    const meta = VISITOR_STATUS_META[visitor.status];
                    return (
                      <tr key={visitor.id} className="transition hover:bg-ink-50/70 dark:hover:bg-ink-800/30">
                        <Td>
                          <p className="text-sm font-semibold text-ink-900 dark:text-ink-100">{visitor.full_name}</p>
                          <p className="text-[10px] text-ink-400">{visitor.phone ?? visitor.email ?? "No contact"}</p>
                        </Td>
                        <Td className="text-xs">{visitor.host_unit?.label ?? "—"}</Td>
                        <Td className="max-w-[220px] truncate text-xs">{visitor.purpose ?? "—"}</Td>
                        <Td className="whitespace-nowrap text-[11px] text-ink-500 dark:text-ink-400">{formatDateTime(visitor.expected_arrival)}</Td>
                        <Td>
                          <div className="flex items-center gap-1.5">
                            <Badge tone={meta.tone} dot>{meta.label}</Badge>
                            {visitor.active_permit_count > 0 ? <Badge tone="info">{visitor.active_permit_count} permits</Badge> : null}
                          </div>
                        </Td>
                        <Td align="right">
                          <div className="flex flex-wrap justify-end gap-1">
                            {isManager && visitor.status === "pending" ? (
                              <>
                                <Button size="sm" variant="subtle" icon="check" onClick={() => actionMutation.mutate({ visitorId: visitor.id, action: "approve" })}>Approve</Button>
                                <Button size="sm" variant="ghost" icon="x" onClick={() => setVisitorToReject(visitor)}>Reject</Button>
                              </>
                            ) : null}
                            {isManager && visitor.status === "approved" ? (
                              <Button size="sm" variant="subtle" icon="play" onClick={() => actionMutation.mutate({ visitorId: visitor.id, action: "check-in" })}>Check in</Button>
                            ) : null}
                            {isManager && visitor.status === "checked_in" ? (
                              <Button size="sm" variant="outline" icon="logout" onClick={() => actionMutation.mutate({ visitorId: visitor.id, action: "check-out" })}>Check out</Button>
                            ) : null}
                            {isManager ? (
                              <Button size="sm" variant="ghost" icon="key" onClick={() => openPermitModal(visitor)}>Permit</Button>
                            ) : null}
                          </div>
                        </Td>
                      </tr>
                    );
                  })}
                </tbody>
              </TableShell>
              {visitorsQuery.data ? (
                <Pagination
                  page={visitorsQuery.data.page}
                  pages={visitorsQuery.data.pages}
                  total={visitorsQuery.data.total}
                  pageSize={pageSize}
                  onPageChange={setPage}
                  onPageSizeChange={(size) => { setPageSize(size); setPage(1); }}
                />
              ) : null}
            </>
          )
        ) : (permitsQuery.data?.items ?? []).length === 0 ? (
          <EmptyState
            icon="key"
            title="No permits issued"
            description="Issue a temporary permit to authorise a visitor's vehicle at the barrier."
            action={isManager ? <Button icon="plus" onClick={() => openPermitModal()}>Issue permit</Button> : undefined}
          />
        ) : (
          <>
            <TableShell>
              <thead>
                <tr>
                  <Th>Permit</Th>
                  <Th>Visitor</Th>
                  <Th>Vehicle</Th>
                  <Th>Valid window</Th>
                  <Th>Entries</Th>
                  <Th>Status</Th>
                  {isManager ? <Th align="right">Actions</Th> : null}
                </tr>
              </thead>
              <tbody>
                {(permitsQuery.data?.items ?? []).map((permit) => {
                  const meta = PERMIT_STATUS_META[permit.status];
                  return (
                    <tr key={permit.id} className="transition hover:bg-ink-50/70 dark:hover:bg-ink-800/30">
                      <Td>
                        <p className="font-mono text-xs font-semibold text-ink-900 dark:text-ink-100">{permit.permit_code}</p>
                        <p className="text-[10px] capitalize text-ink-400">{permit.permit_type.replace("_", " ")}</p>
                      </Td>
                      <Td className="text-xs">
                        {permit.visitor?.full_name ?? "—"}
                        <p className="text-[10px] text-ink-400">{permit.host_unit?.label ?? ""}</p>
                      </Td>
                      <Td>
                        {permit.vehicle_plate ? (
                          <span className="rounded border border-ink-300 bg-white px-1.5 py-0.5 font-mono text-[10px] font-bold dark:border-ink-600 dark:bg-ink-950">{permit.vehicle_plate}</span>
                        ) : (
                          <span className="text-[11px] text-ink-400">Pedestrian</span>
                        )}
                      </Td>
                      <Td className="whitespace-nowrap text-[11px] text-ink-500 dark:text-ink-400">
                        {formatDateTime(permit.start_at)}
                        <span className="mx-1 text-ink-300">→</span>
                        {formatDateTime(permit.end_at)}
                      </Td>
                      <Td>
                        <div className="flex items-center gap-2">
                          <div className="h-1.5 w-16 overflow-hidden rounded-full bg-ink-100 dark:bg-ink-800">
                            <div
                              className="h-full rounded-full bg-brand-500"
                              style={{ width: `${Math.min(100, (permit.entries_used / Math.max(permit.max_entries, 1)) * 100)}%` }}
                            />
                          </div>
                          <span className="text-[10px] text-ink-500 dark:text-ink-400">{permit.entries_used}/{permit.max_entries}</span>
                        </div>
                      </Td>
                      <Td><Badge tone={meta.tone} dot>{meta.label}</Badge></Td>
                      {isManager ? (
                        <Td align="right">
                          <div className="flex justify-end gap-1">
                            {permit.status === "active" || permit.status === "pending" ? (
                              <>
                                <Button size="sm" variant="ghost" icon="visitors" onClick={() => actionMutation.mutate({ visitorId: permit.visitor_id, action: "check-in" })}>Check in</Button>
                                <Button size="sm" variant="ghost" icon="x" onClick={() => { setPermitToRevoke(permit); setRevokeReason("Permit no longer required"); }}>Revoke</Button>
                              </>
                            ) : (
                              <span className="text-[10px] text-ink-400">{permit.revoked_reason ?? "Closed"}</span>
                            )}
                          </div>
                        </Td>
                      ) : null}
                    </tr>
                  );
                })}
              </tbody>
            </TableShell>
            {permitsQuery.data ? (
              <Pagination
                page={permitsQuery.data.page}
                pages={permitsQuery.data.pages}
                total={permitsQuery.data.total}
                pageSize={pageSize}
                onPageChange={setPage}
                onPageSizeChange={(size) => { setPageSize(size); setPage(1); }}
              />
            ) : null}
          </>
        )}
      </Card>

      <Modal
        open={visitorOpen}
        onClose={() => setVisitorOpen(false)}
        title={isManager ? "Register a visitor" : "Request a visitor"}
        description={isManager ? "Create the visitor record, then issue a temporary permit." : "Security will review your request before a permit is issued."}
        size="lg"
        footer={
          <>
            <Button variant="outline" onClick={() => setVisitorOpen(false)}>Cancel</Button>
            <Button
              onClick={() => createVisitorMutation.mutate()}
              loading={createVisitorMutation.isPending}
              disabled={!visitorForm.full_name.trim() || !(visitorForm.host_unit_id || defaultUnitId)}
            >
              {isManager ? "Register visitor" : "Send request"}
            </Button>
          </>
        }
      >
        <div className="grid gap-4 sm:grid-cols-2">
          <Input label="Full name" required value={visitorForm.full_name} onChange={(event) => setVisitorForm({ ...visitorForm, full_name: event.target.value })} placeholder="Visitor name" />
          <Input label="Phone" value={visitorForm.phone} onChange={(event) => setVisitorForm({ ...visitorForm, phone: event.target.value })} placeholder="+20 100 000 0000" />
          <Input label="Email" type="email" value={visitorForm.email} onChange={(event) => setVisitorForm({ ...visitorForm, email: event.target.value })} placeholder="visitor@example.com" />
          <Input label="Company" value={visitorForm.company} onChange={(event) => setVisitorForm({ ...visitorForm, company: event.target.value })} placeholder="Optional" />
          <Select
            label="Host unit"
            required
            value={visitorForm.host_unit_id || defaultUnitId}
            onChange={(event) => setVisitorForm({ ...visitorForm, host_unit_id: event.target.value })}
            disabled={!isManager}
          >
            <option value="">Select a unit…</option>
            {unitOptions.map((unit) => (
              <option key={unit.id} value={unit.id}>{unit.building ? `${unit.building} · ` : ""}{unit.label}</option>
            ))}
          </Select>
          <Input
            label="Expected arrival"
            type="datetime-local"
            value={visitorForm.expected_arrival}
            onChange={(event) => setVisitorForm({ ...visitorForm, expected_arrival: event.target.value })}
          />
          <Input label="Purpose" value={visitorForm.purpose} onChange={(event) => setVisitorForm({ ...visitorForm, purpose: event.target.value })} placeholder="Family visit, delivery, maintenance…" className="sm:col-span-2" />
          <Textarea label="Notes" value={visitorForm.notes} onChange={(event) => setVisitorForm({ ...visitorForm, notes: event.target.value })} className="sm:col-span-2" />
        </div>
      </Modal>

      <Modal
        open={permitOpen}
        onClose={() => setPermitOpen(false)}
        title="Issue a temporary permit"
        description="The gate validates the window and the entry budget on every pass."
        size="lg"
        footer={
          <>
            <Button variant="outline" onClick={() => setPermitOpen(false)}>Cancel</Button>
            <Button
              onClick={() => permitMutation.mutate()}
              loading={permitMutation.isPending}
              disabled={!permitForm.visitor_id || !permitForm.start_at || !permitForm.end_at}
            >
              Issue permit
            </Button>
          </>
        }
      >
        <div className="grid gap-4 sm:grid-cols-2">
          <Select
            label="Visitor"
            required
            value={permitForm.visitor_id}
            onChange={(event) => {
              const visitor = visitorDirectory.data?.items.find((item) => item.id === event.target.value);
              setPermitForm({
                ...permitForm,
                visitor_id: event.target.value,
                host_unit_id: visitor?.host_unit_id ?? permitForm.host_unit_id,
              });
            }}
            className="sm:col-span-2"
          >
            <option value="">Select a visitor…</option>
            {(visitorDirectory.data?.items ?? [])
              .filter((visitor) => !["rejected", "cancelled"].includes(visitor.status))
              .map((visitor) => (
                <option key={visitor.id} value={visitor.id}>
                  {visitor.full_name} · {visitor.host_unit?.label ?? "unit"} · {visitor.status}
                </option>
              ))}
          </Select>
          <Select
            label="Host unit"
            value={permitForm.host_unit_id || defaultUnitId}
            onChange={(event) => setPermitForm({ ...permitForm, host_unit_id: event.target.value })}
          >
            <option value="">Select a unit…</option>
            {unitOptions.map((unit) => (
              <option key={unit.id} value={unit.id}>{unit.building ? `${unit.building} · ` : ""}{unit.label}</option>
            ))}
          </Select>
          <Select label="Permit type" value={permitForm.permit_type} onChange={(event) => setPermitForm({ ...permitForm, permit_type: event.target.value })}>
            <option value="visitor">Visitor</option>
            <option value="contractor">Contractor</option>
            <option value="delivery">Delivery</option>
            <option value="temporary_resident">Temporary resident</option>
            <option value="event">Event</option>
          </Select>
          <Input label="Starts" type="datetime-local" required value={permitForm.start_at} onChange={(event) => setPermitForm({ ...permitForm, start_at: event.target.value })} />
          <Input label="Expires" type="datetime-local" required value={permitForm.end_at} onChange={(event) => setPermitForm({ ...permitForm, end_at: event.target.value })} />
          <Input label="Maximum entries" type="number" min={1} max={100} value={permitForm.max_entries} onChange={(event) => setPermitForm({ ...permitForm, max_entries: event.target.value })} />
          <Input
            label="Vehicle plate"
            value={permitForm.vehicle_plate}
            onChange={(event) => setPermitForm({ ...permitForm, vehicle_plate: event.target.value.toUpperCase() })}
            placeholder="Optional · CAI 1234"
            className="font-mono"
          />
          <Textarea label="Notes" value={permitForm.notes} onChange={(event) => setPermitForm({ ...permitForm, notes: event.target.value })} className="sm:col-span-2" />
        </div>
      </Modal>

      <Modal
        open={permitToRevoke !== null}
        onClose={() => setPermitToRevoke(null)}
        title="Revoke permit"
        description={permitToRevoke ? `${permitToRevoke.permit_code} · ${permitToRevoke.visitor?.full_name ?? ""}` : undefined}
        footer={
          <>
            <Button variant="outline" onClick={() => setPermitToRevoke(null)}>Cancel</Button>
            <Button
              variant="danger"
              loading={revokeMutation.isPending}
              disabled={revokeReason.trim().length < 3}
              onClick={() => permitToRevoke && revokeMutation.mutate({ permitId: permitToRevoke.id, reason: revokeReason })}
            >
              Revoke permit
            </Button>
          </>
        }
      >
        <Textarea label="Reason" required value={revokeReason} onChange={(event) => setRevokeReason(event.target.value)} />
        <p className="mt-2 flex items-start gap-1.5 text-[11px] text-ink-400">
          <Icon name="info" className="mt-0.5 h-3 w-3 shrink-0" />
          Revoked permits are rejected immediately by the gate controller, including any cached lane.
        </p>
      </Modal>

      <ConfirmDialog
        open={visitorToReject !== null}
        onClose={() => setVisitorToReject(null)}
        onConfirm={() => visitorToReject && actionMutation.mutate({ visitorId: visitorToReject.id, action: "reject" })}
        loading={actionMutation.isPending}
        title="Reject visitor request"
        description={`Reject the request from ${visitorToReject?.full_name ?? "this visitor"}? They will not be able to receive a permit.`}
        confirmLabel="Reject request"
      />
    </div>
  );
}
