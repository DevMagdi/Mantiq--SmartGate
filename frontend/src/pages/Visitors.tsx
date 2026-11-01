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
import { useI18n } from "@/i18n";
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
  updatePermit,
  uploadVisitorPhoto,
  visitorAction,
  type PermitPayload,
  type VisitorPayload,
} from "@/services/visitors";
import { apiErrorMessage, mediaUrl } from "@/services/api";
import type { Permit, Visitor, VisitorStatus } from "@/types/models";
import { PERMIT_STATUS_META, VISITOR_STATUS_META } from "@/utils/constants";
import { formatDateTime, initials, plusHours, toDateTimeLocal } from "@/utils/format";

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
  const { t } = useI18n();
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
  const [visitorPhoto, setVisitorPhoto] = useState<File | null>(null);
  const [visitorPhotoPreview, setVisitorPhotoPreview] = useState<string | null>(null);

  const clearVisitorPhoto = (): void => {
    setVisitorPhoto(null);
    setVisitorPhotoPreview((current) => {
      if (current) URL.revokeObjectURL(current);
      return null;
    });
  };
  const [permitOpen, setPermitOpen] = useState(false);
  const [editingPermit, setEditingPermit] = useState<Permit | null>(null);
  const [permitForm, setPermitForm] = useState<PermitForm>(EMPTY_PERMIT);
  const [permitToRevoke, setPermitToRevoke] = useState<Permit | null>(null);
  const [revokeReason, setRevokeReason] = useState("");
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

  const unitOptions = units.data?.items ?? (myProfile.data ? [{ id: myProfile.data.unit_id, label: myProfile.data.unit?.label ?? t("visitors.my_unit"), building: myProfile.data.unit?.building ?? "" }] : []);
  const defaultUnitId = myProfile.data?.unit_id ?? unitOptions[0]?.id ?? "";

  const invalidate = async (): Promise<void> => {
    await queryClient.invalidateQueries({ queryKey: ["visitors"] });
    await queryClient.invalidateQueries({ queryKey: ["permits"] });
    await queryClient.invalidateQueries({ queryKey: ["dashboard"] });
  };

  const createVisitorMutation = useMutation({
    mutationFn: async (): Promise<{ photoFailed: boolean }> => {
      if (!compound && isManager) throw new Error(t("visitors.error.no_compound"));
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
      const visitor = await createVisitor(payload);
      // The photo is a separate multipart endpoint; a failure must not lose the
      // visitor that was just registered.
      if (visitorPhoto) {
        try {
          await uploadVisitorPhoto(visitor.id, visitorPhoto);
        } catch {
          return { photoFailed: true };
        }
      }
      return { photoFailed: false };
    },
    onSuccess: async ({ photoFailed }) => {
      if (photoFailed) {
        toast.error(t("visitors.toast.photo_failed"), t("visitors.toast.photo_failed_hint"));
      }
      toast.success(
        t("visitors.toast.created"),
        isManager ? t("visitors.toast.created_hint_manager") : t("visitors.toast.created_hint_resident"),
      );
      setVisitorOpen(false);
      setVisitorForm(EMPTY_VISITOR);
      clearVisitorPhoto();
      await invalidate();
    },
    onError: (error) => toast.error(t("visitors.toast.create_error"), apiErrorMessage(error)),
  });

  const actionMutation = useMutation({
    mutationFn: ({ visitorId, action }: { visitorId: string; action: VisitorAction }) => visitorAction(visitorId, action),
    onSuccess: async (_visitor, variables) => {
      toast.success(t("visitors.toast.action_done", { action: t(`visitors.action.${variables.action === "check-in" ? "check_in" : variables.action === "check-out" ? "check_out" : variables.action}`) }));
      setVisitorToReject(null);
      await invalidate();
    },
    onError: (error) => toast.error(t("visitors.toast.action_error"), apiErrorMessage(error)),
  });

  const permitMutation = useMutation({
    mutationFn: async (): Promise<void> => {
      const visitor = visitorDirectory.data?.items.find((item) => item.id === permitForm.visitor_id);
      const shared = {
        start_at: new Date(permitForm.start_at).toISOString(),
        end_at: new Date(permitForm.end_at).toISOString(),
        permit_type: permitForm.permit_type as PermitPayload["permit_type"],
        max_entries: Number(permitForm.max_entries) || 1,
        notes: permitForm.notes.trim() || null,
      };
      if (editingPermit) {
        // Permits keep their visitor/unit/plate once issued — only the window,
        // type, entry allowance and notes are editable.
        await updatePermit(editingPermit.id, shared);
        return;
      }
      await createPermit({
        ...shared,
        visitor_id: permitForm.visitor_id,
        host_unit_id: permitForm.host_unit_id || visitor?.host_unit_id || defaultUnitId,
        vehicle_plate: permitForm.vehicle_plate.trim() || null,
      });
    },
    onSuccess: async () => {
      if (editingPermit) {
        toast.success(t("visitors.toast.permit_updated"), t("visitors.toast.permit_updated_hint"));
      } else {
        toast.success(t("visitors.toast.permit_issued"), t("visitors.toast.permit_issued_hint"));
      }
      setPermitOpen(false);
      setEditingPermit(null);
      setPermitForm(EMPTY_PERMIT);
      await invalidate();
    },
    onError: (error) => toast.error(t("visitors.toast.permit_error"), apiErrorMessage(error)),
  });

  const revokeMutation = useMutation({
    mutationFn: ({ permitId, reason }: { permitId: string; reason: string }) => revokePermit(permitId, reason),
    onSuccess: async () => {
      toast.success(t("visitors.toast.revoked"));
      setPermitToRevoke(null);
      await invalidate();
    },
    onError: (error) => toast.error(t("visitors.toast.revoke_error"), apiErrorMessage(error)),
  });

  const openVisitorModal = (): void => {
    setVisitorForm({ ...EMPTY_VISITOR, host_unit_id: defaultUnitId });
    setVisitorOpen(true);
  };

  const openPermitModal = (visitor?: Visitor): void => {
    setEditingPermit(null);
    setPermitForm({
      ...EMPTY_PERMIT,
      visitor_id: visitor?.id ?? "",
      host_unit_id: visitor?.host_unit_id ?? defaultUnitId,
    });
    setPermitOpen(true);
  };

  const openPermitEditor = (permit: Permit): void => {
    setEditingPermit(permit);
    setPermitForm({
      visitor_id: permit.visitor_id,
      host_unit_id: permit.host_unit_id,
      start_at: toDateTimeLocal(new Date(permit.start_at)),
      end_at: toDateTimeLocal(new Date(permit.end_at)),
      permit_type: permit.permit_type,
      max_entries: String(permit.max_entries),
      vehicle_plate: permit.vehicle_plate ?? "",
      notes: permit.notes ?? "",
    });
    setPermitOpen(true);
  };

  const activeQuery = tab === "visitors" ? visitorsQuery : permitsQuery;
  const totalVisitors = visitorsQuery.data?.total;

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow={isManager ? t("visitors.eyebrow.manager") : t("visitors.eyebrow.resident")}
        title={isManager ? t("visitors.title.manager") : t("visitors.title.resident")}
        subtitle={t("visitors.subtitle")}
        actions={
          <>
            {isManager ? (
              <Button variant="outline" icon="key" onClick={() => openPermitModal()}>
                {t("visitors.issue_permit")}
              </Button>
            ) : null}
            <Button icon="plus" onClick={openVisitorModal}>
              {isManager ? t("visitors.register") : t("visitors.request")}
            </Button>
          </>
        }
      />

      <div className="flex flex-wrap items-center justify-between gap-3">
        <Tabs
          tabs={[
            { key: "visitors", label: t("visitors.tab.visitors"), count: totalVisitors },
            { key: "permits", label: t("visitors.tab.permits"), count: permitsQuery.data?.total },
          ]}
          value={tab}
          onChange={(key) => { setTab(key); setStatusFilter(""); }}
        />
        <div className="flex flex-wrap items-center gap-2">
          <SearchInput value={search} onChange={setSearch} placeholder={tab === "visitors" ? t("visitors.search.visitors") : t("visitors.search.permits")} className="w-full sm:w-64" />
          <Select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)} className="w-40">
            <option value="">{t("common.all_statuses")}</option>
            {tab === "visitors"
              ? ["pending", "approved", "checked_in", "checked_out", "rejected", "expired"].map((value) => (
                  <option key={value} value={value}>{t(`status.${value}`)}</option>
                ))
              : ["pending", "active", "expired", "revoked"].map((value) => (
                  <option key={value} value={value}>{t(`status.${value}`)}</option>
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
              title={t("visitors.empty.visitors_title")}
              description={isManager ? t("visitors.empty.visitors_desc_manager") : t("visitors.empty.visitors_desc_resident")}
              action={<Button icon="plus" onClick={openVisitorModal}>{t("visitors.register")}</Button>}
            />
          ) : (
            <>
              <TableShell>
                <thead>
                  <tr>
                    <Th>{t("common.visitor")}</Th>
                    <Th>{t("visitors.table.unit")}</Th>
                    <Th>{t("visitors.table.purpose")}</Th>
                    <Th>{t("visitors.table.expected")}</Th>
                    <Th>{t("common.status")}</Th>
                    <Th align="right">{t("common.actions")}</Th>
                  </tr>
                </thead>
                <tbody>
                  {(visitorsQuery.data?.items ?? []).map((visitor) => {
                    const meta = VISITOR_STATUS_META[visitor.status];
                    return (
                      <tr key={visitor.id} className="transition hover:bg-ink-50/70 dark:hover:bg-ink-800/30">
                        <Td>
                          <div className="flex items-center gap-2.5">
                            {mediaUrl(visitor.photo_url) ? (
                              <img
                                src={mediaUrl(visitor.photo_url)!}
                                alt={t("visitors.form.photo_preview")}
                                className="h-9 w-9 rounded-full border border-ink-200 object-cover dark:border-ink-700"
                                loading="lazy"
                              />
                            ) : (
                              <span className="grid h-9 w-9 place-items-center rounded-full bg-ink-100 text-[11px] font-bold text-ink-500 dark:bg-ink-800 dark:text-ink-300">
                                {initials(visitor.full_name)}
                              </span>
                            )}
                            <div className="min-w-0">
                              <p className="text-sm font-semibold text-ink-900 dark:text-ink-100">{visitor.full_name}</p>
                              <p className="text-[10px] text-ink-400">{visitor.phone ?? visitor.email ?? t("common.no_contact")}</p>
                            </div>
                          </div>
                        </Td>
                        <Td className="text-xs">{visitor.host_unit?.label ?? "—"}</Td>
                        <Td className="max-w-[220px] truncate text-xs">{visitor.purpose ?? "—"}</Td>
                        <Td className="whitespace-nowrap text-[11px] text-ink-500 dark:text-ink-400">{formatDateTime(visitor.expected_arrival)}</Td>
                        <Td>
                          <div className="flex items-center gap-1.5">
                            <Badge tone={meta.tone} dot>{t(`status.${visitor.status}`)}</Badge>
                            {visitor.active_permit_count > 0 ? <Badge tone="info">{t("visitors.permits_count", { count: visitor.active_permit_count })}</Badge> : null}
                          </div>
                        </Td>
                        <Td align="right">
                          <div className="flex flex-wrap justify-end gap-1">
                            {isManager && visitor.status === "pending" ? (
                              <>
                                <Button size="sm" variant="subtle" icon="check" onClick={() => actionMutation.mutate({ visitorId: visitor.id, action: "approve" })}>{t("visitors.action.approve")}</Button>
                                <Button size="sm" variant="ghost" icon="x" onClick={() => setVisitorToReject(visitor)}>{t("visitors.action.reject")}</Button>
                              </>
                            ) : null}
                            {isManager && visitor.status === "approved" ? (
                              <Button size="sm" variant="subtle" icon="play" onClick={() => actionMutation.mutate({ visitorId: visitor.id, action: "check-in" })}>{t("visitors.action.check_in")}</Button>
                            ) : null}
                            {isManager && visitor.status === "checked_in" ? (
                              <Button size="sm" variant="outline" icon="logout" onClick={() => actionMutation.mutate({ visitorId: visitor.id, action: "check-out" })}>{t("visitors.action.check_out")}</Button>
                            ) : null}
                            {isManager ? (
                              <Button size="sm" variant="ghost" icon="key" onClick={() => openPermitModal(visitor)}>{t("visitors.action.permit")}</Button>
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
            title={t("visitors.empty.permits_title")}
            description={t("visitors.empty.permits_desc")}
            action={isManager ? <Button icon="plus" onClick={() => openPermitModal()}>{t("visitors.issue_permit")}</Button> : undefined}
          />
        ) : (
          <>
            <TableShell>
              <thead>
                <tr>
                  <Th>{t("visitors.table.permit")}</Th>
                  <Th>{t("common.visitor")}</Th>
                  <Th>{t("common.vehicle")}</Th>
                  <Th>{t("visitors.table.window")}</Th>
                  <Th>{t("visitors.table.entries")}</Th>
                  <Th>{t("common.status")}</Th>
                  {isManager ? <Th align="right">{t("common.actions")}</Th> : null}
                </tr>
              </thead>
              <tbody>
                {(permitsQuery.data?.items ?? []).map((permit) => {
                  const meta = PERMIT_STATUS_META[permit.status];
                  return (
                    <tr key={permit.id} className="transition hover:bg-ink-50/70 dark:hover:bg-ink-800/30">
                      <Td>
                        <p className="font-mono text-xs font-semibold text-ink-900 dark:text-ink-100">{permit.permit_code}</p>
                        <p className="text-[10px] capitalize text-ink-400">{t(`visitors.permit_type.${permit.permit_type}`)}</p>
                      </Td>
                      <Td className="text-xs">
                        {permit.visitor?.full_name ?? "—"}
                        <p className="text-[10px] text-ink-400">{permit.host_unit?.label ?? ""}</p>
                      </Td>
                      <Td>
                        {permit.vehicle_plate ? (
                          <span className="rounded border border-ink-300 bg-white px-1.5 py-0.5 font-mono text-[10px] font-bold dark:border-ink-600 dark:bg-ink-950">{permit.vehicle_plate}</span>
                        ) : (
                          <span className="text-[11px] text-ink-400">{t("visitors.pedestrian")}</span>
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
                      <Td><Badge tone={meta.tone} dot>{t(`status.${permit.status}`)}</Badge></Td>
                      {isManager ? (
                        <Td align="right">
                          <div className="flex justify-end gap-1">
                            {permit.status === "active" || permit.status === "pending" ? (
                              <>
                                <Button size="sm" variant="ghost" icon="visitors" onClick={() => actionMutation.mutate({ visitorId: permit.visitor_id, action: "check-in" })}>{t("visitors.action.check_in")}</Button>
                                <Button size="sm" variant="ghost" icon="edit" onClick={() => openPermitEditor(permit)}>{t("common.edit")}</Button>
                                <Button size="sm" variant="ghost" icon="x" onClick={() => { setPermitToRevoke(permit); setRevokeReason(t("visitors.revoke.default_reason")); }}>{t("visitors.action.revoke")}</Button>
                              </>
                            ) : (
                              <span className="text-[10px] text-ink-400">{permit.revoked_reason ?? t("visitors.closed")}</span>
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
        title={isManager ? t("visitors.modal.register_title") : t("visitors.modal.request_title")}
        description={isManager ? t("visitors.modal.register_desc") : t("visitors.modal.request_desc")}
        size="lg"
        footer={
          <>
            <Button variant="outline" onClick={() => setVisitorOpen(false)}>{t("common.cancel")}</Button>
            <Button
              onClick={() => createVisitorMutation.mutate()}
              loading={createVisitorMutation.isPending}
              disabled={!visitorForm.full_name.trim() || !(visitorForm.host_unit_id || defaultUnitId)}
            >
              {isManager ? t("visitors.register") : t("visitors.modal.send")}
            </Button>
          </>
        }
      >
        <div className="grid gap-4 sm:grid-cols-2">
          <Input label={t("settings.user.full_name")} required value={visitorForm.full_name} onChange={(event) => setVisitorForm({ ...visitorForm, full_name: event.target.value })} placeholder={t("visitors.form.name_placeholder")} />
          <Input label={t("common.phone")} value={visitorForm.phone} onChange={(event) => setVisitorForm({ ...visitorForm, phone: event.target.value })} placeholder="+20 100 000 0000" />
          <Input label={t("common.email")} type="email" value={visitorForm.email} onChange={(event) => setVisitorForm({ ...visitorForm, email: event.target.value })} placeholder="visitor@example.com" />
          <Input label={t("visitors.form.company")} value={visitorForm.company} onChange={(event) => setVisitorForm({ ...visitorForm, company: event.target.value })} placeholder="Optional" />
          <Select
            label={t("visitors.table.unit")}
            required
            value={visitorForm.host_unit_id || defaultUnitId}
            onChange={(event) => setVisitorForm({ ...visitorForm, host_unit_id: event.target.value })}
            disabled={!isManager}
          >
            <option value="">{t("visitors.form.select_unit")}</option>
            {unitOptions.map((unit) => (
              <option key={unit.id} value={unit.id}>{unit.building ? `${unit.building} · ` : ""}{unit.label}</option>
            ))}
          </Select>
          <Input
            label={t("visitors.form.expected")}
            type="datetime-local"
            value={visitorForm.expected_arrival}
            onChange={(event) => setVisitorForm({ ...visitorForm, expected_arrival: event.target.value })}
          />
          <Input label={t("visitors.table.purpose")} value={visitorForm.purpose} onChange={(event) => setVisitorForm({ ...visitorForm, purpose: event.target.value })} placeholder={t("visitors.form.purpose_placeholder")} className="sm:col-span-2" />
          <div className="sm:col-span-2">
            <label className="field-label" htmlFor="visitor-photo">{t("visitors.form.photo")}</label>
            <div className="flex items-center gap-3">
              {visitorPhotoPreview ? (
                <img
                  src={visitorPhotoPreview}
                  alt={t("visitors.form.photo_preview")}
                  className="h-16 w-16 rounded-xl border border-ink-200 object-cover dark:border-ink-700"
                />
              ) : (
                <span className="grid h-16 w-16 place-items-center rounded-xl border border-dashed border-ink-300 text-ink-400 dark:border-ink-700">
                  <Icon name="camera" className="h-5 w-5" />
                </span>
              )}
              <div className="min-w-0 flex-1">
                <input
                  id="visitor-photo"
                  type="file"
                  accept="image/*"
                  onChange={(event) => {
                    const file = event.target.files?.[0] ?? null;
                    setVisitorPhoto(file);
                    setVisitorPhotoPreview((current) => {
                      if (current) URL.revokeObjectURL(current);
                      return file ? URL.createObjectURL(file) : null;
                    });
                  }}
                  className="block w-full cursor-pointer rounded-xl border border-dashed border-ink-300 bg-ink-50/60 px-3 py-2 text-xs text-ink-500 file:mr-3 file:rounded-lg file:border-0 file:bg-brand-50 file:px-2.5 file:py-1.5 file:text-xs file:font-semibold file:text-brand-700 dark:border-ink-700 dark:bg-ink-950/40 dark:text-ink-400 dark:file:bg-brand-500/10 dark:file:text-brand-300"
                />
                <p className="mt-1 text-[11px] text-ink-400">{t("visitors.form.photo_hint")}</p>
              </div>
            </div>
          </div>
          <Textarea label={t("common.notes")} value={visitorForm.notes} onChange={(event) => setVisitorForm({ ...visitorForm, notes: event.target.value })} className="sm:col-span-2" />
        </div>
      </Modal>

      <Modal
        open={permitOpen}
        onClose={() => { setPermitOpen(false); setEditingPermit(null); }}
        title={editingPermit ? t("visitors.permit.edit_title") : t("visitors.permit.issue_title")}
        description={editingPermit ? t("visitors.permit.edit_desc") : t("visitors.permit.issue_desc")}
        size="lg"
        footer={
          <>
            <Button variant="outline" onClick={() => setPermitOpen(false)}>{t("common.cancel")}</Button>
            <Button
              onClick={() => permitMutation.mutate()}
              loading={permitMutation.isPending}
              disabled={
                !permitForm.visitor_id ||
                !permitForm.start_at ||
                !permitForm.end_at ||
                (!editingPermit && !(permitForm.host_unit_id || defaultUnitId))
              }
            >
              {editingPermit ? t("common.save_changes") : t("visitors.issue_permit")}
            </Button>
          </>
        }
      >
        <div className="grid gap-4 sm:grid-cols-2">
          <Select
            label={t("common.visitor")}
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
            disabled={editingPermit !== null}
          >
            <option value="">{t("visitors.form.select_visitor")}</option>
            {(visitorDirectory.data?.items ?? [])
              .filter((visitor) => !["rejected", "cancelled"].includes(visitor.status))
              .map((visitor) => (
                <option key={visitor.id} value={visitor.id}>
                  {visitor.full_name} · {visitor.host_unit?.label ?? "unit"} · {visitor.status}
                </option>
              ))}
          </Select>
          <Select
            label={t("visitors.table.unit")}
            value={permitForm.host_unit_id || defaultUnitId}
            onChange={(event) => setPermitForm({ ...permitForm, host_unit_id: event.target.value })}
            disabled={editingPermit !== null}
          >
            <option value="">{t("visitors.form.select_unit")}</option>
            {unitOptions.map((unit) => (
              <option key={unit.id} value={unit.id}>{unit.building ? `${unit.building} · ` : ""}{unit.label}</option>
            ))}
          </Select>
          <Select label={t("visitors.form.permit_type")} value={permitForm.permit_type} onChange={(event) => setPermitForm({ ...permitForm, permit_type: event.target.value })}>
            <option value="visitor">{t("visitors.permit_type.visitor")}</option>
            <option value="contractor">{t("visitors.permit_type.contractor")}</option>
            <option value="delivery">{t("visitors.permit_type.delivery")}</option>
            <option value="temporary_resident">{t("visitors.permit_type.temporary_resident")}</option>
            <option value="event">{t("visitors.permit_type.event")}</option>
          </Select>
          <Input label={t("visitors.form.start")} type="datetime-local" required value={permitForm.start_at} onChange={(event) => setPermitForm({ ...permitForm, start_at: event.target.value })} />
          <Input label={t("common.expires")} type="datetime-local" required value={permitForm.end_at} onChange={(event) => setPermitForm({ ...permitForm, end_at: event.target.value })} />
          <Input label={t("visitors.form.max_entries")} type="number" min={1} max={100} value={permitForm.max_entries} onChange={(event) => setPermitForm({ ...permitForm, max_entries: event.target.value })} />
          <Input
            label={t("visitors.form.vehicle_plate")}
            value={permitForm.vehicle_plate}
            onChange={(event) => setPermitForm({ ...permitForm, vehicle_plate: event.target.value.toUpperCase() })}
            placeholder={t("visitors.form.vehicle_placeholder")}
            className="font-mono"
            disabled={editingPermit !== null}
          />
          <Textarea label={t("common.notes")} value={permitForm.notes} onChange={(event) => setPermitForm({ ...permitForm, notes: event.target.value })} className="sm:col-span-2" />
        </div>
      </Modal>

      <Modal
        open={permitToRevoke !== null}
        onClose={() => setPermitToRevoke(null)}
        title={t("visitors.revoke.title")}
        description={permitToRevoke ? `${permitToRevoke.permit_code} · ${permitToRevoke.visitor?.full_name ?? ""}` : undefined}
        footer={
          <>
            <Button variant="outline" onClick={() => setPermitToRevoke(null)}>{t("common.cancel")}</Button>
            <Button
              variant="danger"
              loading={revokeMutation.isPending}
              disabled={revokeReason.trim().length < 3}
              onClick={() => permitToRevoke && revokeMutation.mutate({ permitId: permitToRevoke.id, reason: revokeReason })}
            >
              {t("visitors.revoke.confirm")}
            </Button>
          </>
        }
      >
        <Textarea label={t("common.reason")} required value={revokeReason} onChange={(event) => setRevokeReason(event.target.value)} />
        <p className="mt-2 flex items-start gap-1.5 text-[11px] text-ink-400">
          <Icon name="info" className="mt-0.5 h-3 w-3 shrink-0" />
          {t("visitors.revoke.note")}
        </p>
      </Modal>

      <ConfirmDialog
        open={visitorToReject !== null}
        onClose={() => setVisitorToReject(null)}
        onConfirm={() => visitorToReject && actionMutation.mutate({ visitorId: visitorToReject.id, action: "reject" })}
        loading={actionMutation.isPending}
        title={t("visitors.reject.title")}
        description={t("visitors.reject.description", { name: visitorToReject?.full_name ?? t("common.visitor") })}
        confirmLabel={t("visitors.reject.confirm")}
      />
    </div>
  );
}
