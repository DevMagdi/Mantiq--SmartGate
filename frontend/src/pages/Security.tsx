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
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { useToast } from "@/hooks/useToast";
import { listCompounds } from "@/services/admin";
import { listResidents } from "@/services/registry";
import {
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
      if (!compound) throw new Error("No compound available");
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
      toast.success("Blacklist entry created", "The decision engine applies it immediately.");
      setBlacklistOpen(false);
      setBlacklistForm(EMPTY_BLACKLIST);
      await invalidate();
    },
    onError: (error) => toast.error("Could not create entry", apiErrorMessage(error)),
  });

  const toggleEntryMutation = useMutation({
    mutationFn: (entry: BlacklistEntry) => updateBlacklistEntry(entry.id, { is_active: !entry.is_active }),
    onSuccess: async (entry) => {
      toast.success(entry.is_active ? "Entry re-activated" : "Entry deactivated");
      await invalidate();
    },
    onError: (error) => toast.error("Update failed", apiErrorMessage(error)),
  });

  const deleteEntryMutation = useMutation({
    mutationFn: (entry: BlacklistEntry) => deleteBlacklistEntry(entry.id),
    onSuccess: async () => {
      toast.success("Blacklist entry deleted");
      setEntryToDelete(null);
      await invalidate();
    },
    onError: (error) => toast.error("Delete failed", apiErrorMessage(error)),
  });

  const enrollMutation = useMutation({
    mutationFn: async (): Promise<void> => {
      if (!enrollFile) throw new Error("Choose a face photo");
      if (!enrollResident) throw new Error("Select a resident");
      await enrollFace(enrollResident, enrollFile, overwrite);
    },
    onSuccess: async () => {
      toast.success("Face enrolled", "The gallery is hot-reloaded for the vision workers.");
      setEnrollOpen(false);
      setEnrollFile(null);
      setEnrollResident("");
      setOverwrite(false);
      await invalidate();
      await queryClient.invalidateQueries({ queryKey: ["cv-status"] });
    },
    onError: (error) => toast.error("Enrollment failed", apiErrorMessage(error)),
  });

  const deactivateFaceMutation = useMutation({
    mutationFn: (face: FaceEmbedding) => deactivateFace(face.id),
    onSuccess: async () => {
      toast.success("Embedding deactivated");
      await invalidate();
    },
    onError: (error) => toast.error("Update failed", apiErrorMessage(error)),
  });

  const deleteFaceMutation = useMutation({
    mutationFn: (face: FaceEmbedding) => deleteFace(face.id),
    onSuccess: async () => {
      toast.success("Face embedding deleted");
      setFaceToDelete(null);
      await invalidate();
    },
    onError: (error) => toast.error("Delete failed", apiErrorMessage(error)),
  });

  const refreshGallery = useMutation({
    mutationFn: refreshFaceGallery,
    onSuccess: async () => {
      toast.success("Gallery refresh requested");
      await queryClient.invalidateQueries({ queryKey: ["face-gallery"] });
    },
    onError: (error) => toast.error("Refresh failed", apiErrorMessage(error)),
  });

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Security policies"
        title="Blacklist & face recognition"
        subtitle="Block plates and individuals, and manage the biometric gallery used for resident identification."
        actions={
          <>
            <Button variant="outline" icon="refresh" onClick={() => refreshGallery.mutate()} loading={refreshGallery.isPending}>
              Refresh gallery
            </Button>
            <Button variant="outline" icon="camera" onClick={() => setEnrollOpen(true)}>
              Enroll face
            </Button>
            <Button icon="plus" onClick={() => setBlacklistOpen(true)}>
              Add blacklist entry
            </Button>
          </>
        }
      />

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard label="Active blacklist" value={activeBlacklist.data?.total ?? "—"} icon="shield" tone="danger" hint={`${blacklistQuery.data?.total ?? 0} total entries`} />
        <StatCard label="Face embeddings" value={gallery.data?.total_embeddings ?? "—"} icon="users" tone="success" hint={`${gallery.data?.active_embeddings ?? 0} active vectors`} />
        <StatCard label="Enrolled residents" value={gallery.data?.enrolled_residents ?? "—"} icon="check" tone="info" hint={gallery.data?.model_name ? `Model ${gallery.data.model_name}` : "Model loading"} />
        <StatCard
          label="Vision engine"
          value={cvStatus.data?.mode ?? "—"}
          icon="sparkles"
          tone={cvStatus.data?.engine_ready ? "brand" : "warning"}
          hint={cvStatus.data?.engine_ready ? `Threshold ${formatPercent(cvStatus.data.similarity_threshold)}` : "Warming up"}
        />
      </div>

      {cvStatus.data && cvStatus.data.warnings.length > 0 ? (
        <Card className="border-amber-200 bg-amber-50/70 p-3 dark:border-amber-500/30 dark:bg-amber-500/5">
          <div className="flex items-start gap-2 text-xs text-amber-800 dark:text-amber-200">
            <Icon name="alert" className="mt-0.5 h-4 w-4 shrink-0" />
            <div>
              <p className="font-semibold">Vision engine notices</p>
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
            { key: "blacklist", label: "Blacklist", count: blacklistQuery.data?.total },
            { key: "faces", label: "Face gallery", count: facesQuery.data?.total },
          ]}
          value={tab}
          onChange={(key) => { setTab(key); setTypeFilter(""); }}
        />
        <div className="flex items-center gap-2">
          <SearchInput value={search} onChange={setSearch} placeholder={tab === "blacklist" ? "Search plates or people…" : "Search residents…"} className="w-full sm:w-64" />
          {tab === "blacklist" ? (
            <Select value={typeFilter} onChange={(event) => setTypeFilter(event.target.value)} className="w-32">
              <option value="">All types</option>
              <option value="plate">Plate</option>
              <option value="person">Person</option>
              <option value="face">Face</option>
            </Select>
          ) : null}
        </div>
      </div>

      {tab === "blacklist" ? (
        <Card>
          {blacklistQuery.isLoading ? (
            <LoadingBlock />
          ) : (blacklistQuery.data?.items ?? []).length === 0 ? (
            <EmptyState icon="shield" title="Blacklist is empty" description="Add a plate or person to block them at every gate." action={<Button icon="plus" onClick={() => setBlacklistOpen(true)}>Add entry</Button>} />
          ) : (
            <>
              <TableShell>
                <thead>
                  <tr>
                    <Th>Type</Th>
                    <Th>Identifier</Th>
                    <Th>Reason</Th>
                    <Th>Description</Th>
                    <Th>Expires</Th>
                    <Th>Status</Th>
                    <Th align="right">Actions</Th>
                  </tr>
                </thead>
                <tbody>
                  {(blacklistQuery.data?.items ?? []).map((entry) => (
                    <tr key={entry.id} className="transition hover:bg-ink-50/70 dark:hover:bg-ink-800/30">
                      <Td><Badge tone={BLACKLIST_TYPE_META[entry.entry_type].tone}>{BLACKLIST_TYPE_META[entry.entry_type].label}</Badge></Td>
                      <Td>
                        <p className="font-mono text-xs font-semibold uppercase">{entry.plate_number ?? entry.person_name ?? entry.resident?.full_name ?? "—"}</p>
                        {entry.national_id ? <p className="text-[10px] text-ink-400">NID {entry.national_id}</p> : null}
                      </Td>
                      <Td className="text-xs capitalize">{entry.reason.replace("_", " ")}</Td>
                      <Td className="max-w-[240px] truncate text-xs text-ink-500 dark:text-ink-400">{entry.description ?? "—"}</Td>
                      <Td className="text-[11px] text-ink-500 dark:text-ink-400">{entry.expires_at ? formatDate(entry.expires_at) : "Permanent"}</Td>
                      <Td><Badge tone={entry.is_active ? "danger" : "neutral"} dot>{entry.is_active ? "Active" : "Inactive"}</Badge></Td>
                      <Td align="right">
                        <div className="flex justify-end gap-1">
                          <Button size="sm" variant="ghost" onClick={() => toggleEntryMutation.mutate(entry)}>
                            {entry.is_active ? "Deactivate" : "Activate"}
                          </Button>
                          {isAdmin || entry.is_active ? (
                            <Button size="icon" variant="ghost" onClick={() => setEntryToDelete(entry)} aria-label="Delete entry">
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
            <LoadingBlock label="Loading face gallery…" />
          ) : (facesQuery.data?.items ?? []).length === 0 ? (
            <EmptyState icon="users" title="No faces enrolled" description="Enroll a resident photo to enable face-based entry." action={<Button icon="camera" onClick={() => setEnrollOpen(true)}>Enroll face</Button>} />
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
                          <Badge tone={face.is_active ? "success" : "neutral"} dot>{face.is_active ? "Active" : "Inactive"}</Badge>
                        </div>
                      </div>
                      <div className="space-y-2 p-3">
                        <div>
                          <p className="text-sm font-semibold text-ink-900 dark:text-ink-100">{face.resident?.full_name ?? "Unlinked"}</p>
                          <p className="text-[10px] text-ink-400">
                            {face.dimension}-d · {face.model_name} · {formatDate(face.created_at)}
                          </p>
                        </div>
                        <div className="flex items-center justify-between text-[10px] text-ink-400">
                          <span>Quality {formatPercent(face.quality)}</span>
                          <span>{face.similarity_to_existing !== null ? `Sim ${formatPercent(face.similarity_to_existing)}` : ""}</span>
                        </div>
                        <div className="flex gap-1">
                          <Button size="sm" variant="outline" className="flex-1" onClick={() => deactivateFaceMutation.mutate(face)} disabled={!face.is_active}>
                            Deactivate
                          </Button>
                          <Button size="icon" variant="ghost" onClick={() => setFaceToDelete(face)} aria-label="Delete face">
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
        title="Add a blacklist entry"
        description="Matching plates or faces are denied access at every gate in the compound."
        footer={
          <>
            <Button variant="outline" onClick={() => setBlacklistOpen(false)}>Cancel</Button>
            <Button
              onClick={() => createBlacklistMutation.mutate()}
              loading={createBlacklistMutation.isPending}
              disabled={blacklistForm.entry_type === "plate" ? blacklistForm.plate_number.trim().length < 2 : !blacklistForm.person_name.trim() && !blacklistForm.national_id.trim()}
            >
              Add to blacklist
            </Button>
          </>
        }
      >
        <div className="grid gap-4 sm:grid-cols-2">
          <Select label="Entry type" value={blacklistForm.entry_type} onChange={(event) => setBlacklistForm({ ...blacklistForm, entry_type: event.target.value as BlacklistEntryType })}>
            <option value="plate">Vehicle plate</option>
            <option value="person">Person</option>
            <option value="face">Face (biometric)</option>
          </Select>
          <Select label="Reason" value={blacklistForm.reason} onChange={(event) => setBlacklistForm({ ...blacklistForm, reason: event.target.value as BlacklistReason })}>
            <option value="security">Security</option>
            <option value="theft">Theft</option>
            <option value="trespassing">Trespassing</option>
            <option value="unpaid_dues">Unpaid dues</option>
            <option value="court_order">Court order</option>
            <option value="other">Other</option>
          </Select>
          {blacklistForm.entry_type === "plate" ? (
            <Input
              label="Plate number"
              required
              value={blacklistForm.plate_number}
              onChange={(event) => setBlacklistForm({ ...blacklistForm, plate_number: event.target.value.toUpperCase() })}
              placeholder="CAI 1234"
              className="sm:col-span-2 font-mono"
            />
          ) : (
            <>
              <Input label="Person name" value={blacklistForm.person_name} onChange={(event) => setBlacklistForm({ ...blacklistForm, person_name: event.target.value })} placeholder="Full name" />
              <Input label="National ID" value={blacklistForm.national_id} onChange={(event) => setBlacklistForm({ ...blacklistForm, national_id: event.target.value })} placeholder="Optional" />
            </>
          )}
          <Input
            label="Expires at"
            type="datetime-local"
            value={blacklistForm.expires_at}
            onChange={(event) => setBlacklistForm({ ...blacklistForm, expires_at: event.target.value })}
            hint="Leave empty for a permanent block"
            className="sm:col-span-2"
          />
          <Textarea label="Description" value={blacklistForm.description} onChange={(event) => setBlacklistForm({ ...blacklistForm, description: event.target.value })} className="sm:col-span-2" placeholder="Case reference, officer note…" />
        </div>
      </Modal>

      <Modal
        open={enrollOpen}
        onClose={() => setEnrollOpen(false)}
        title="Enroll a resident face"
        description="A clear, front-facing photo produces the best 512-d embedding."
        footer={
          <>
            <Button variant="outline" onClick={() => setEnrollOpen(false)}>Cancel</Button>
            <Button onClick={() => enrollMutation.mutate()} loading={enrollMutation.isPending} disabled={!enrollFile || !enrollResident}>
              Enroll face
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          <Select label="Resident" required value={enrollResident} onChange={(event) => setEnrollResident(event.target.value)}>
            <option value="">Select a resident…</option>
            {(residents.data?.items ?? []).map((resident) => (
              <option key={resident.id} value={resident.id}>
                {resident.full_name} · {resident.unit?.label ?? "unit"}
              </option>
            ))}
          </Select>
          <div>
            <label className="field-label">Face photo</label>
            <input
              type="file"
              accept="image/*"
              onChange={(event) => setEnrollFile(event.target.files?.[0] ?? null)}
              className="block w-full cursor-pointer rounded-xl border border-dashed border-ink-300 bg-ink-50/60 px-3 py-4 text-xs text-ink-500 file:mr-3 file:rounded-lg file:border-0 file:bg-brand-50 file:px-2.5 file:py-1.5 file:text-xs file:font-semibold file:text-brand-700 dark:border-ink-700 dark:bg-ink-950/40 dark:text-ink-400 dark:file:bg-brand-500/10 dark:file:text-brand-300"
            />
          </div>
          <label className="flex items-center gap-2 text-xs text-ink-600 dark:text-ink-300">
            <input
              type="checkbox"
              checked={overwrite}
              onChange={(event) => setOverwrite(event.target.checked)}
              className="h-4 w-4 rounded border-ink-300 text-brand-600 focus:ring-brand-500"
            />
            Replace existing embeddings for this resident
          </label>
          <div className="rounded-xl border border-ink-200 p-3 text-[11px] leading-relaxed text-ink-500 dark:border-ink-700 dark:text-ink-400">
            <p className="flex items-center gap-1.5 font-semibold text-ink-700 dark:text-ink-200">
              <Icon name="camera" className="h-3.5 w-3.5" /> Capture checklist
            </p>
            <ul className="mt-1 list-inside list-disc">
              <li>One face, front facing, eyes visible</li>
              <li>Good lighting, no sunglasses or masks</li>
              <li>At least 200×200 pixels</li>
            </ul>
          </div>
        </div>
      </Modal>

      <ConfirmDialog
        open={entryToDelete !== null}
        onClose={() => setEntryToDelete(null)}
        onConfirm={() => entryToDelete && deleteEntryMutation.mutate(entryToDelete)}
        loading={deleteEntryMutation.isPending}
        title="Delete blacklist entry"
        description={`Remove ${entryToDelete?.plate_number ?? entryToDelete?.person_name ?? "this entry"} from the blacklist?`}
        confirmLabel="Delete entry"
      />

      <ConfirmDialog
        open={faceToDelete !== null}
        onClose={() => setFaceToDelete(null)}
        onConfirm={() => faceToDelete && deleteFaceMutation.mutate(faceToDelete)}
        loading={deleteFaceMutation.isPending}
        title="Delete face embedding"
        description="The resident will no longer be recognised by the camera until a new photo is enrolled."
        confirmLabel="Delete embedding"
      />
    </div>
  );
}
