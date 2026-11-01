import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Icon } from "@/components/Icon";
import { PageHeader } from "@/components/PageHeader";
import { StatCard } from "@/components/StatCard";
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
import { listResidents } from "@/services/registry";
import {
  checkFaceQuality,
  createBlacklistEntry,
  deactivateFace,
  deleteBlacklistEntry,
  deleteFace,
  enrollFace,
  fetchFaceGallery,
  listBlacklist,
  listFaces,
  refreshFaceGallery,
  updateBlacklistEntry,
  type BlacklistPayload,
} from "@/services/security";
import { fetchCvStatus } from "@/services/cv";
import { apiErrorMessage, mediaUrl } from "@/services/api";
import type {
  BlacklistEntry,
  BlacklistEntryType,
  BlacklistReason,
  FaceEmbedding,
  FaceQualityReport,
} from "@/types/models";
import { BLACKLIST_TYPE_META } from "@/utils/constants";
import { formatDate, formatPercent } from "@/utils/format";

type TabKey = "blacklist" | "faces";

interface BlacklistForm {
  entry_type: BlacklistEntryType;
  plate_number: string;
  person_name: string;
  national_id: string;
  reason: BlacklistReason;
  description: string;
  expires_at: string;
}

const EMPTY_BLACKLIST: BlacklistForm = {
  entry_type: "plate",
  plate_number: "",
  person_name: "",
  national_id: "",
  reason: "security",
  description: "",
  expires_at: "",
};

export function SecurityPage(): JSX.Element {
  const { t } = useI18n();
  const { hasRole } = useAuth();
  const isAdmin = hasRole("admin");
  const toast = useToast();
  const queryClient = useQueryClient();

  const [tab, setTab] = useState<TabKey>("blacklist");
  const [search, setSearch] = useState("");
  const debouncedSearch = useDebouncedValue(search);
  const [typeFilter, setTypeFilter] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);

  const [blacklistOpen, setBlacklistOpen] = useState(false);
  const [blacklistForm, setBlacklistForm] = useState<BlacklistForm>(EMPTY_BLACKLIST);
  const [entryToDelete, setEntryToDelete] = useState<BlacklistEntry | null>(null);

  const [enrollOpen, setEnrollOpen] = useState(false);
  const [enrollResident, setEnrollResident] = useState("");
  const [enrollFile, setEnrollFile] = useState<File | null>(null);
  const [enrollReport, setEnrollReport] = useState<FaceQualityReport | null>(null);
  const [overwrite, setOverwrite] = useState(false);
  const [faceToDelete, setFaceToDelete] = useState<FaceEmbedding | null>(null);

  useEffect(() => {
    setPage(1);
  }, [debouncedSearch, typeFilter, tab]);

  const compounds = useQuery({ queryKey: ["compounds"], queryFn: listCompounds });
  const compound = compounds.data?.items[0];

  const activeBlacklist = useQuery({
    queryKey: ["blacklist", "active-count"],
    queryFn: () => listBlacklist({ page: 1, page_size: 1, is_active: true }),
  });

  const blacklistQuery = useQuery({
    queryKey: ["blacklist", { debouncedSearch, typeFilter, page, pageSize }],
    queryFn: () =>
      listBlacklist({
        page,
        page_size: pageSize,
        search: debouncedSearch || undefined,
        entry_type: typeFilter || undefined,
      }),
    enabled: tab === "blacklist",
  });

  const facesQuery = useQuery({
    queryKey: ["faces", { debouncedSearch, page, pageSize }],
    queryFn: () => listFaces({ page, page_size: pageSize, search: debouncedSearch || undefined }),
    enabled: tab === "faces",
  });

  const gallery = useQuery({ queryKey: ["face-gallery"], queryFn: fetchFaceGallery });
  const cvStatus = useQuery({ queryKey: ["cv-status"], queryFn: fetchCvStatus, retry: false });
  const residents = useQuery({
    queryKey: ["residents", "directory"],
    queryFn: () => listResidents({ page_size: 200, sort_by: "full_name", sort_dir: "asc" }),
    enabled: enrollOpen,
  });

  const invalidate = async (): Promise<void> => {
    await queryClient.invalidateQueries({ queryKey: ["blacklist"] });
    await queryClient.invalidateQueries({ queryKey: ["faces"] });
    await queryClient.invalidateQueries({ queryKey: ["face-gallery"] });
    await queryClient.invalidateQueries({ queryKey: ["dashboard"] });
  };

  const createBlacklistMutation = useMutation({
    mutationFn: async (): Promise<void> => {
      if (!compound) throw new Error(t("security.error.no_compound"));
      const payload: BlacklistPayload = {
        compound_id: compound.id,
        entry_type: blacklistForm.entry_type,
        plate_number: blacklistForm.entry_type === "plate" ? blacklistForm.plate_number.trim() : null,
        person_name: blacklistForm.entry_type !== "plate" ? blacklistForm.person_name.trim() || null : null,
        national_id: blacklistForm.entry_type !== "plate" ? blacklistForm.national_id.trim() || null : null,
        reason: blacklistForm.reason,
        description: blacklistForm.description.trim() || null,
        expires_at: blacklistForm.expires_at ? new Date(blacklistForm.expires_at).toISOString() : null,
      };
      await createBlacklistEntry(payload);
    },
    onSuccess: async () => {
      toast.success(t("security.toast.entry_created"), t("security.toast.entry_created_hint"));
      setBlacklistOpen(false);
      setBlacklistForm(EMPTY_BLACKLIST);
      await invalidate();
    },
    onError: (error) => toast.error(t("security.toast.entry_error"), apiErrorMessage(error)),
  });

  const toggleEntryMutation = useMutation({
    mutationFn: (entry: BlacklistEntry) => updateBlacklistEntry(entry.id, { is_active: !entry.is_active }),
    onSuccess: async (entry) => {
      toast.success(entry.is_active ? t("security.toast.entry_reactivated") : t("security.toast.entry_deactivated"));
      await invalidate();
    },
    onError: (error) => toast.error(t("settings.toast.update_failed"), apiErrorMessage(error)),
  });

  const deleteEntryMutation = useMutation({
    mutationFn: (entry: BlacklistEntry) => deleteBlacklistEntry(entry.id),
    onSuccess: async () => {
      toast.success(t("security.toast.entry_deleted"));
      setEntryToDelete(null);
      await invalidate();
    },
    onError: (error) => toast.error(t("security.toast.delete_failed"), apiErrorMessage(error)),
  });

  // Pre-flight the photo through POST /faces/quality-check before enrolling:
  // the API rejects an enrollment that fails these gates, so we surface the
  // exact reason here instead of failing after the upload.
  const qualityMutation = useMutation({
    mutationFn: ({ residentId, file }: { residentId: string; file: File }) =>
      checkFaceQuality(residentId, file),
    onSuccess: (report) => setEnrollReport(report),
    onError: (error) => {
      setEnrollReport(null);
      toast.error(t("security.toast.quality_failed"), apiErrorMessage(error));
    },
  });

  const runQualityCheck = (residentId: string, file: File | null): void => {
    setEnrollReport(null);
    if (!residentId || !file) return;
    qualityMutation.mutate({ residentId, file });
  };

  const enrollMutation = useMutation({
    mutationFn: async (): Promise<void> => {
      if (!enrollFile) throw new Error(t("security.error.choose_photo"));
      if (!enrollResident) throw new Error(t("security.error.select_resident"));
      await enrollFace(enrollResident, enrollFile, overwrite);
    },
    onSuccess: async () => {
      toast.success(t("security.toast.face_enrolled"), t("security.toast.face_enrolled_hint"));
      setEnrollOpen(false);
      setEnrollFile(null);
      setEnrollReport(null);
      setEnrollResident("");
      setOverwrite(false);
      await invalidate();
      await queryClient.invalidateQueries({ queryKey: ["cv-status"] });
    },
    onError: (error) => toast.error(t("security.toast.enroll_failed"), apiErrorMessage(error)),
  });

  const deactivateFaceMutation = useMutation({
    mutationFn: (face: FaceEmbedding) => deactivateFace(face.id),
    onSuccess: async () => {
      toast.success(t("security.toast.embedding_deactivated"));
      await invalidate();
    },
    onError: (error) => toast.error(t("settings.toast.update_failed"), apiErrorMessage(error)),
  });

  const deleteFaceMutation = useMutation({
    mutationFn: (face: FaceEmbedding) => deleteFace(face.id),
    onSuccess: async () => {
      toast.success(t("security.toast.face_deleted"));
      setFaceToDelete(null);
      await invalidate();
    },
    onError: (error) => toast.error(t("security.toast.delete_failed"), apiErrorMessage(error)),
  });

  const refreshGallery = useMutation({
    mutationFn: refreshFaceGallery,
    onSuccess: async () => {
      toast.success(t("security.toast.gallery_requested"));
      await queryClient.invalidateQueries({ queryKey: ["face-gallery"] });
    },
    onError: (error) => toast.error(t("security.toast.refresh_failed"), apiErrorMessage(error)),
  });

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow={t("security.eyebrow")}
        title={t("security.title")}
        subtitle={t("security.subtitle")}
        actions={
          <>
            <Button variant="outline" icon="refresh" onClick={() => refreshGallery.mutate()} loading={refreshGallery.isPending}>
              {t("security.refresh_gallery")}
            </Button>
            <Button variant="outline" icon="camera" onClick={() => setEnrollOpen(true)}>
              {t("security.enroll_face")}
            </Button>
            <Button icon="plus" onClick={() => setBlacklistOpen(true)}>
              {t("security.add_entry")}
            </Button>
          </>
        }
      />

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard label={t("security.stat.active_blacklist")} value={activeBlacklist.data?.total ?? "—"} icon="shield" tone="danger" hint={t("security.stat.active_blacklist_hint", { count: blacklistQuery.data?.total ?? 0 })} />
        <StatCard label={t("security.stat.embeddings")} value={gallery.data?.total_embeddings ?? "—"} icon="users" tone="success" hint={t("security.stat.embeddings_hint", { count: gallery.data?.active_embeddings ?? 0 })} />
        <StatCard label={t("security.stat.enrolled")} value={gallery.data?.enrolled_residents ?? "—"} icon="check" tone="info" hint={gallery.data?.model_name ? t("security.stat.enrolled_hint", { model: gallery.data.model_name }) : t("security.stat.model_loading")} />
        <StatCard
          label={t("security.stat.engine")}
          value={cvStatus.data?.mode ?? "—"}
          icon="sparkles"
          tone={cvStatus.data?.engine_ready ? "brand" : "warning"}
          hint={cvStatus.data?.engine_ready ? t("security.stat.engine_threshold", { value: formatPercent(cvStatus.data.similarity_threshold) }) : t("security.stat.engine_warming")}
        />
      </div>

      {cvStatus.data && cvStatus.data.warnings.length > 0 ? (
        <Card className="border-amber-200 bg-amber-50/70 p-3 dark:border-amber-500/30 dark:bg-amber-500/5">
          <div className="flex items-start gap-2 text-xs text-amber-800 dark:text-amber-200">
            <Icon name="alert" className="mt-0.5 h-4 w-4 shrink-0" />
            <div>
              <p className="font-semibold">{t("security.notices")}</p>
              <ul className="mt-1 list-inside list-disc space-y-0.5">
                {cvStatus.data.warnings.map((warning) => (
                  <li key={warning}>{warning}</li>
                ))}
              </ul>
            </div>
          </div>
        </Card>
      ) : null}

      <div className="flex flex-wrap items-center justify-between gap-3">
        <Tabs
          tabs={[
            { key: "blacklist", label: t("security.tab.blacklist"), count: blacklistQuery.data?.total },
            { key: "faces", label: t("security.tab.faces"), count: facesQuery.data?.total },
          ]}
          value={tab}
          onChange={(key) => { setTab(key); setTypeFilter(""); }}
        />
        <div className="flex items-center gap-2">
          <SearchInput value={search} onChange={setSearch} placeholder={tab === "blacklist" ? t("security.search.blacklist") : t("security.search.faces")} className="w-full sm:w-64" />
          {tab === "blacklist" ? (
            <Select value={typeFilter} onChange={(event) => setTypeFilter(event.target.value)} className="w-32">
              <option value="">{t("security.filter.all_types")}</option>
              <option value="plate">{t("security.entry_type.plate")}</option>
              <option value="person">{t("security.entry_type.person")}</option>
              <option value="face">{t("security.entry_type.face")}</option>
            </Select>
          ) : null}
        </div>
      </div>

      {tab === "blacklist" ? (
        <Card>
          {blacklistQuery.isLoading ? (
            <LoadingBlock />
          ) : (blacklistQuery.data?.items ?? []).length === 0 ? (
            <EmptyState icon="shield" title={t("security.blacklist.empty_title")} description={t("security.blacklist.empty_description")} action={<Button icon="plus" onClick={() => setBlacklistOpen(true)}>{t("security.blacklist.add_entry")}</Button>} />
          ) : (
            <>
              <TableShell>
                <thead>
                  <tr>
                    <Th>{t("common.type")}</Th>
                    <Th>{t("security.table.identifier")}</Th>
                    <Th>{t("common.reason")}</Th>
                    <Th>{t("security.table.description")}</Th>
                    <Th>{t("common.expires")}</Th>
                    <Th>{t("common.status")}</Th>
                    <Th align="right">{t("common.actions")}</Th>
                  </tr>
                </thead>
                <tbody>
                  {(blacklistQuery.data?.items ?? []).map((entry) => (
                    <tr key={entry.id} className="transition hover:bg-ink-50/70 dark:hover:bg-ink-800/30">
                      <Td><Badge tone={BLACKLIST_TYPE_META[entry.entry_type].tone}>{t(`security.entry_type.${entry.entry_type}`)}</Badge></Td>
                      <Td>
                        <p className="font-mono text-xs font-semibold uppercase">{entry.plate_number ?? entry.person_name ?? entry.resident?.full_name ?? "—"}</p>
                        {entry.national_id ? <p className="text-[10px] text-ink-400">NID {entry.national_id}</p> : null}
                      </Td>
                      <Td className="text-xs capitalize">{t(`security.reason.${entry.reason}`)}</Td>
                      <Td className="max-w-[240px] truncate text-xs text-ink-500 dark:text-ink-400">{entry.description ?? "—"}</Td>
                      <Td className="text-[11px] text-ink-500 dark:text-ink-400">{entry.expires_at ? formatDate(entry.expires_at) : t("common.permanent")}</Td>
                      <Td><Badge tone={entry.is_active ? "danger" : "neutral"} dot>{entry.is_active ? t("common.active") : t("common.inactive")}</Badge></Td>
                      <Td align="right">
                        <div className="flex justify-end gap-1">
                          <Button size="sm" variant="ghost" onClick={() => toggleEntryMutation.mutate(entry)}>
                            {entry.is_active ? t("common.disable") : t("security.action.activate")}
                          </Button>
                          {isAdmin || entry.is_active ? (
                            <Button size="icon" variant="ghost" onClick={() => setEntryToDelete(entry)} aria-label={t("security.action.delete_entry")}>
                              <Icon name="trash" className="h-4 w-4 text-rose-500" />
                            </Button>
                          ) : null}
                        </div>
                      </Td>
                    </tr>
                  ))}
                </tbody>
              </TableShell>
              {blacklistQuery.data ? (
                <Pagination
                  page={blacklistQuery.data.page}
                  pages={blacklistQuery.data.pages}
                  total={blacklistQuery.data.total}
                  pageSize={pageSize}
                  onPageChange={setPage}
                  onPageSizeChange={(size) => { setPageSize(size); setPage(1); }}
                />
              ) : null}
            </>
          )}
        </Card>
      ) : (
        <Card>
          {facesQuery.isLoading ? (
            <LoadingBlock label={t("security.faces.loading")} />
          ) : (facesQuery.data?.items ?? []).length === 0 ? (
            <EmptyState icon="users" title={t("security.faces.empty_title")} description={t("security.faces.empty_description")} action={<Button icon="camera" onClick={() => setEnrollOpen(true)}>{t("security.enroll_face")}</Button>} />
          ) : (
            <>
              <div className="grid gap-3 p-4 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-4">
                {(facesQuery.data?.items ?? []).map((face) => {
                  const image = mediaUrl(face.image_url);
                  return (
                    <div key={face.id} className="overflow-hidden rounded-xl border border-ink-200 bg-white dark:border-ink-800 dark:bg-ink-900">
                      <div className="relative aspect-[4/3] bg-ink-100 dark:bg-ink-800">
                        {image ? (
                          <img src={image} alt={face.resident?.full_name ?? "Face"} className="h-full w-full object-cover" loading="lazy" />
                        ) : (
                          <span className="grid h-full place-items-center text-ink-400">
                            <Icon name="users" className="h-6 w-6" />
                          </span>
                        )}
                        <div className="absolute start-2 top-2">
                          <Badge tone={face.is_active ? "success" : "neutral"} dot>{face.is_active ? t("common.active") : t("common.inactive")}</Badge>
                        </div>
                      </div>
                      <div className="space-y-2 p-3">
                        <div>
                          <p className="text-sm font-semibold text-ink-900 dark:text-ink-100">{face.resident?.full_name ?? t("security.faces.unlinked")}</p>
                          <p className="text-[10px] text-ink-400">
                            {face.dimension}-d · {face.model_name} · {formatDate(face.created_at)}
                          </p>
                        </div>
                        <div className="flex items-center justify-between text-[10px] text-ink-400">
                          <span>{t("security.faces.quality", { value: formatPercent(face.quality) })}</span>
                          <span>{face.similarity_to_existing !== null ? t("security.faces.similarity", { value: formatPercent(face.similarity_to_existing) }) : ""}</span>
                        </div>
                        <div className="flex gap-1">
                          <Button size="sm" variant="outline" className="flex-1" onClick={() => deactivateFaceMutation.mutate(face)} disabled={!face.is_active}>
                            {t("common.disable")}
                          </Button>
                          <Button size="icon" variant="ghost" onClick={() => setFaceToDelete(face)} aria-label={t("security.faces.delete_aria")}>
                            <Icon name="trash" className="h-4 w-4 text-rose-500" />
                          </Button>
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
              {facesQuery.data ? (
                <Pagination
                  page={facesQuery.data.page}
                  pages={facesQuery.data.pages}
                  total={facesQuery.data.total}
                  pageSize={pageSize}
                  onPageChange={setPage}
                  onPageSizeChange={(size) => { setPageSize(size); setPage(1); }}
                />
              ) : null}
            </>
          )}
        </Card>
      )}

      <Modal
        open={blacklistOpen}
        onClose={() => setBlacklistOpen(false)}
        title={t("security.modal.entry_title")}
        description={t("security.modal.entry_description")}
        footer={
          <>
            <Button variant="outline" onClick={() => setBlacklistOpen(false)}>{t("common.cancel")}</Button>
            <Button
              onClick={() => createBlacklistMutation.mutate()}
              loading={createBlacklistMutation.isPending}
              disabled={blacklistForm.entry_type === "plate" ? blacklistForm.plate_number.trim().length < 2 : !blacklistForm.person_name.trim() && !blacklistForm.national_id.trim()}
            >
              {t("security.modal.add_to_blacklist")}
            </Button>
          </>
        }
      >
        <div className="grid gap-4 sm:grid-cols-2">
          <Select label={t("security.form.entry_type")} value={blacklistForm.entry_type} onChange={(event) => setBlacklistForm({ ...blacklistForm, entry_type: event.target.value as BlacklistEntryType })}>
            <option value="plate">{t("security.entry_type.plate")}</option>
            <option value="person">{t("security.entry_type.person")}</option>
            <option value="face">{t("security.entry_type.face")}</option>
          </Select>
          <Select label={t("common.reason")} value={blacklistForm.reason} onChange={(event) => setBlacklistForm({ ...blacklistForm, reason: event.target.value as BlacklistReason })}>
            <option value="security">{t("security.reason.security")}</option>
            <option value="theft">{t("security.reason.theft")}</option>
            <option value="trespassing">{t("security.reason.trespassing")}</option>
            <option value="unpaid_dues">{t("security.reason.unpaid_dues")}</option>
            <option value="court_order">{t("security.reason.court_order")}</option>
            <option value="other">{t("security.reason.other")}</option>
          </Select>
          {blacklistForm.entry_type === "plate" ? (
            <Input
              label={t("security.form.plate")}
              required
              value={blacklistForm.plate_number}
              onChange={(event) => setBlacklistForm({ ...blacklistForm, plate_number: event.target.value.toUpperCase() })}
              placeholder="CAI 1234"
              className="sm:col-span-2 font-mono"
            />
          ) : (
            <>
              <Input label={t("security.form.person")} value={blacklistForm.person_name} onChange={(event) => setBlacklistForm({ ...blacklistForm, person_name: event.target.value })} placeholder={t("security.form.full_name")} />
              <Input label={t("security.form.national_id")} value={blacklistForm.national_id} onChange={(event) => setBlacklistForm({ ...blacklistForm, national_id: event.target.value })} placeholder="Optional" />
            </>
          )}
          <Input
            label={t("security.form.expires_at")}
            type="datetime-local"
            value={blacklistForm.expires_at}
            onChange={(event) => setBlacklistForm({ ...blacklistForm, expires_at: event.target.value })}
            hint={t("security.form.expires_hint")}
            className="sm:col-span-2"
          />
          <Textarea label={t("security.form.description")} value={blacklistForm.description} onChange={(event) => setBlacklistForm({ ...blacklistForm, description: event.target.value })} className="sm:col-span-2" placeholder={t("security.form.description_placeholder")} />
        </div>
      </Modal>

      <Modal
        open={enrollOpen}
        onClose={() => {
          setEnrollOpen(false);
          setEnrollFile(null);
          setEnrollReport(null);
        }}
        title={t("security.modal.enroll_title")}
        description={t("security.modal.enroll_description")}
        footer={
          <>
            <Button variant="outline" onClick={() => setEnrollOpen(false)}>{t("common.cancel")}</Button>
            <Button
              onClick={() => enrollMutation.mutate()}
              loading={enrollMutation.isPending}
              disabled={
                !enrollFile ||
                !enrollResident ||
                qualityMutation.isPending ||
                (enrollReport !== null && !enrollReport.passed)
              }
            >
              {t("security.enroll_face")}
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          <Select
            label={t("security.form.resident")}
            required
            value={enrollResident}
            onChange={(event) => {
              setEnrollResident(event.target.value);
              runQualityCheck(event.target.value, enrollFile);
            }}
          >
            <option value="">{t("security.form.select_resident")}</option>
            {(residents.data?.items ?? []).map((resident) => (
              <option key={resident.id} value={resident.id}>
                {resident.full_name} · {resident.unit?.label ?? "unit"}
              </option>
            ))}
          </Select>
          <div>
            <label className="field-label">{t("security.form.face_photo")}</label>
            <input
              type="file"
              accept="image/*"
              onChange={(event) => {
                const file = event.target.files?.[0] ?? null;
                setEnrollFile(file);
                runQualityCheck(enrollResident, file);
              }}
              className="block w-full cursor-pointer rounded-xl border border-dashed border-ink-300 bg-ink-50/60 px-3 py-4 text-xs text-ink-500 file:mr-3 file:rounded-lg file:border-0 file:bg-brand-50 file:px-2.5 file:py-1.5 file:text-xs file:font-semibold file:text-brand-700 dark:border-ink-700 dark:bg-ink-950/40 dark:text-ink-400 dark:file:bg-brand-500/10 dark:file:text-brand-300"
            />
          </div>
          {qualityMutation.isPending ? (
            <div className="rounded-xl border border-ink-200 p-3 dark:border-ink-700">
              <LoadingBlock label={t("security.quality.checking")} />
            </div>
          ) : null}

          {enrollReport ? (
            <div
              className={
                enrollReport.passed
                  ? "rounded-xl border border-brand-300 bg-brand-50/70 p-3 dark:border-brand-500/40 dark:bg-brand-500/10"
                  : "rounded-xl border border-rose-300 bg-rose-50/70 p-3 dark:border-rose-500/40 dark:bg-rose-500/10"
              }
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="flex items-center gap-2 text-xs font-semibold">
                  <Icon
                    name={enrollReport.passed ? "check" : "alert"}
                    className={enrollReport.passed ? "h-4 w-4 text-brand-600" : "h-4 w-4 text-rose-600"}
                  />
                  {enrollReport.passed
                    ? t("security.quality.passed")
                    : t("security.quality.failed")}
                </p>
                <Badge tone={enrollReport.passed ? "success" : "danger"}>
                  {t("security.quality.score", { value: Math.round(enrollReport.score) })}
                </Badge>
              </div>
              <p className="mt-1 text-[11px] text-ink-500 dark:text-ink-400">
                {t("security.quality.details", {
                  faces: enrollReport.face_count,
                  width: enrollReport.width,
                  height: enrollReport.height,
                })}
              </p>
              <p className="text-[11px] text-ink-500 dark:text-ink-400">
                {t("security.quality.metrics", {
                  blur: Math.round(enrollReport.blur),
                  brightness: Math.round(enrollReport.brightness),
                })}
              </p>
              {enrollReport.issues.length > 0 ? (
                <ul className="mt-2 space-y-1">
                  {enrollReport.issues.map((issue) => (
                    <li key={issue.code} className="flex items-start gap-1.5 text-[11px] leading-relaxed">
                      <Icon
                        name={issue.severity === "error" ? "x" : "alert"}
                        className={
                          issue.severity === "error"
                            ? "mt-0.5 h-3 w-3 shrink-0 text-rose-500"
                            : "mt-0.5 h-3 w-3 shrink-0 text-amber-500"
                        }
                      />
                      <span>
                        <span className="font-semibold">{t(`security.quality.issue.${issue.code}`)}</span>
                        {issue.hint ? ` — ${issue.hint}` : ` — ${issue.message}`}
                      </span>
                    </li>
                  ))}
                </ul>
              ) : null}
              {!enrollReport.passed ? (
                <p className="mt-2 text-[11px] font-medium text-rose-600 dark:text-rose-300">
                  {t("security.quality.blocked")}
                </p>
              ) : null}
            </div>
          ) : null}

          <label className="flex items-center gap-2 text-xs text-ink-600 dark:text-ink-300">
            <input
              type="checkbox"
              checked={overwrite}
              onChange={(event) => setOverwrite(event.target.checked)}
              className="h-4 w-4 rounded border-ink-300 text-brand-600 focus:ring-brand-500"
            />
            {t("security.form.overwrite")}
          </label>
          <div className="rounded-xl border border-ink-200 p-3 text-[11px] leading-relaxed text-ink-500 dark:border-ink-700 dark:text-ink-400">
            <p className="flex items-center gap-1.5 font-semibold text-ink-700 dark:text-ink-200">
              <Icon name="camera" className="h-3.5 w-3.5" /> {t("security.form.checklist")}
            </p>
            <ul className="mt-1 list-inside list-disc">
              <li>{t("security.form.checklist_1")}</li>
              <li>{t("security.form.checklist_2")}</li>
              <li>{t("security.form.checklist_3")}</li>
            </ul>
          </div>
        </div>
      </Modal>

      <ConfirmDialog
        open={entryToDelete !== null}
        onClose={() => setEntryToDelete(null)}
        onConfirm={() => entryToDelete && deleteEntryMutation.mutate(entryToDelete)}
        loading={deleteEntryMutation.isPending}
        title={t("security.delete_entry.title")}
        description={t("security.delete_entry.description", { name: entryToDelete?.plate_number ?? entryToDelete?.person_name ?? t("security.table.identifier") })}
        confirmLabel={t("security.delete_entry.confirm")}
      />

      <ConfirmDialog
        open={faceToDelete !== null}
        onClose={() => setFaceToDelete(null)}
        onConfirm={() => faceToDelete && deleteFaceMutation.mutate(faceToDelete)}
        loading={deleteFaceMutation.isPending}
        title={t("security.delete_face.title")}
        description={t("security.delete_face.description")}
        confirmLabel={t("security.delete_face.confirm")}
      />
    </div>
  );
}
