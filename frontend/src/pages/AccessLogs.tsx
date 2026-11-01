import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Icon } from "@/components/Icon";
import { PageHeader } from "@/components/PageHeader";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  Input,
  LoadingBlock,
  Modal,
  Pagination,
  SearchInput,
  Select,
  TableShell,
  Td,
  Textarea,
  Th,
  cn,
} from "@/components/ui";
import { useAuth } from "@/hooks/useAuth";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { useToast } from "@/hooks/useToast";
import { listGates } from "@/services/admin";
import {
  createManualEntry,
  downloadAccessLogs,
  listAccessLogs,
  overrideAccessLog,
  type AccessLogFilters,
} from "@/services/access";
import { apiErrorMessage, mediaUrl } from "@/services/api";
import type { AccessDecision, AccessDirection, AccessLog } from "@/types/models";
import { DECISION_META, reasonLabel } from "@/utils/constants";
import { formatDateTime, formatPercent } from "@/utils/format";

interface FiltersState {
  decision: string;
  direction: string;
  gateId: string;
  plate: string;
  from: string;
  to: string;
  overridden: string;
}

const EMPTY_FILTERS: FiltersState = {
  decision: "",
  direction: "",
  gateId: "",
  plate: "",
  from: "",
  to: "",
  overridden: "",
};

export function AccessLogsPage(): JSX.Element {
  const { hasRole } = useAuth();
  const isManager = hasRole("admin", "security_officer");
  const toast = useToast();
  const queryClient = useQueryClient();

  const [search, setSearch] = useState("");
  const debouncedSearch = useDebouncedValue(search);
  const [filters, setFilters] = useState<FiltersState>(EMPTY_FILTERS);
  const [showFilters, setShowFilters] = useState(false);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);
  const [selected, setSelected] = useState<AccessLog | null>(null);
  const [overrideDecision, setOverrideDecision] = useState<AccessDecision>("allow");
  const [overrideReason, setOverrideReason] = useState("Verified by the security officer");
  const [overrideOpenGate, setOverrideOpenGate] = useState(true);
  const [manualOpen, setManualOpen] = useState(false);
  const [manualForm, setManualForm] = useState({
    gate_id: "",
    direction: "entry" as AccessDirection,
    decision: "allow" as AccessDecision,
    plate_number: "",
    reason: "Manual gate operation",
    notes: "",
  });

  useEffect(() => {
    setPage(1);
  }, [debouncedSearch, filters, pageSize]);

  const gates = useQuery({ queryKey: ["gates"], queryFn: () => listGates() });
  const gateOptions = gates.data?.items ?? [];

  const params = useMemo<AccessLogFilters>(() => {
    const query: AccessLogFilters = {
      page,
      page_size: pageSize,
      search: debouncedSearch || undefined,
      plate: filters.plate || undefined,
      decision: (filters.decision || undefined) as AccessDecision | undefined,
      direction: (filters.direction || undefined) as AccessDirection | undefined,
      gate_id: filters.gateId || undefined,
      start: filters.from ? new Date(`${filters.from}T00:00:00`).toISOString() : undefined,
      end: filters.to ? new Date(`${filters.to}T23:59:59`).toISOString() : undefined,
      overridden: filters.overridden === "" ? undefined : filters.overridden === "true",
    };
    return query;
  }, [page, pageSize, debouncedSearch, filters]);

  const logsQuery = useQuery({
    queryKey: ["access-logs", params],
    queryFn: () => listAccessLogs(params),
    refetchInterval: 30_000,
  });

  const exportMutation = useMutation({
    mutationFn: (format: "csv" | "xlsx") => downloadAccessLogs(format, { ...params, page: undefined, page_size: undefined }),
    onSuccess: (_data, format) => toast.success(`Export ready (${format.toUpperCase()})`, "Your download should start automatically."),
    onError: (error) => toast.error("Export failed", apiErrorMessage(error)),
  });

  const overrideMutation = useMutation({
    mutationFn: ({ logId }: { logId: string }) =>
      overrideAccessLog(logId, {
        decision: overrideDecision,
        reason: overrideReason,
        open_gate: overrideOpenGate && overrideDecision === "allow",
        notes: "Overridden from the access log view",
      }),
    onSuccess: async (log) => {
      toast.success(`Decision updated to ${log.decision}`);
      setSelected(null);
      await queryClient.invalidateQueries({ queryKey: ["access-logs"] });
      await queryClient.invalidateQueries({ queryKey: ["dashboard"] });
    },
    onError: (error) => toast.error("Override failed", apiErrorMessage(error)),
  });

  const manualMutation = useMutation({
    mutationFn: () =>
      createManualEntry({
        gate_id: manualForm.gate_id || gateOptions[0]?.id || "",
        direction: manualForm.direction,
        decision: manualForm.decision,
        plate_number: manualForm.plate_number.trim() || null,
        reason: manualForm.reason,
        notes: manualForm.notes.trim() || null,
        open_gate: manualForm.decision === "allow",
      }),
    onSuccess: async () => {
      toast.success("Manual gate event recorded");
      setManualOpen(false);
      setManualForm({
        gate_id: gateOptions[0]?.id ?? "",
        direction: "entry",
        decision: "allow",
        plate_number: "",
        reason: "Manual gate operation",
        notes: "",
      });
      await queryClient.invalidateQueries({ queryKey: ["access-logs"] });
      await queryClient.invalidateQueries({ queryKey: ["dashboard"] });
    },
    onError: (error) => toast.error("Could not record manual entry", apiErrorMessage(error)),
  });

  const openDetail = (log: AccessLog): void => {
    setSelected(log);
    setOverrideDecision(log.decision === "deny" ? "allow" : "allow");
    setOverrideReason(log.decision === "deny" ? "Access granted after officer verification" : "Verified by the security officer");
    setOverrideOpenGate(true);
  };

  const activeFilterCount = Object.values(filters).filter(Boolean).length;

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Audit trail"
        title="Access logs"
        subtitle="Every detection and decision, with cropped snapshots, confidence scores and the officer override history."
        actions={
          <>
            <Button variant="outline" icon="download" onClick={() => exportMutation.mutate("csv")} loading={exportMutation.isPending && exportMutation.variables === "csv"}>
              CSV
            </Button>
            <Button variant="outline" icon="download" onClick={() => exportMutation.mutate("xlsx")} loading={exportMutation.isPending && exportMutation.variables === "xlsx"}>
              Excel
            </Button>
            {isManager ? (
              <Button icon="plus" onClick={() => { setManualForm((current) => ({ ...current, gate_id: current.gate_id || gateOptions[0]?.id || "" })); setManualOpen(true); }}>
                Manual entry
              </Button>
            ) : null}
          </>
        }
      />

      <Card className="p-3">
        <div className="flex flex-wrap items-center gap-2">
          <SearchInput value={search} onChange={setSearch} placeholder="Search plate, resident, visitor, reason…" className="min-w-[220px] flex-1" />
          <Select value={filters.decision} onChange={(event) => setFilters({ ...filters, decision: event.target.value })} className="w-36">
            <option value="">All decisions</option>
            <option value="allow">Allow</option>
            <option value="deny">Deny</option>
            <option value="unknown">Unknown</option>
            <option value="review">Review</option>
          </Select>
          <Button
            variant={showFilters ? "subtle" : "outline"}
            icon="filter"
            onClick={() => setShowFilters((current) => !current)}
          >
            Filters{activeFilterCount > 0 ? ` · ${activeFilterCount}` : ""}
          </Button>
          {activeFilterCount > 0 ? (
            <Button variant="ghost" size="sm" onClick={() => setFilters(EMPTY_FILTERS)}>Reset</Button>
          ) : null}
          <Button variant="ghost" size="icon" onClick={() => void logsQuery.refetch()} aria-label="Refresh logs">
            <Icon name="refresh" className={cn("h-4 w-4", logsQuery.isFetching && "animate-spin")} />
          </Button>
        </div>

        {showFilters ? (
          <div className="mt-3 grid gap-3 border-t border-ink-100 pt-3 sm:grid-cols-2 lg:grid-cols-5 dark:border-ink-800">
            <Input label="Plate" value={filters.plate} onChange={(event) => setFilters({ ...filters, plate: event.target.value.toUpperCase() })} placeholder="CAI 4821" />
            <Select label="Direction" value={filters.direction} onChange={(event) => setFilters({ ...filters, direction: event.target.value })}>
              <option value="">Any direction</option>
              <option value="entry">Entry</option>
              <option value="exit">Exit</option>
            </Select>
            <Select label="Gate" value={filters.gateId} onChange={(event) => setFilters({ ...filters, gateId: event.target.value })}>
              <option value="">All gates</option>
              {gateOptions.map((gate) => (
                <option key={gate.id} value={gate.id}>{gate.name}</option>
              ))}
            </Select>
            <Input label="From" type="date" value={filters.from} onChange={(event) => setFilters({ ...filters, from: event.target.value })} />
            <Input label="To" type="date" value={filters.to} onChange={(event) => setFilters({ ...filters, to: event.target.value })} />
            <Select label="Overridden" value={filters.overridden} onChange={(event) => setFilters({ ...filters, overridden: event.target.value })}>
              <option value="">All records</option>
              <option value="true">Overridden only</option>
              <option value="false">Automatic only</option>
            </Select>
          </div>
        ) : null}
      </Card>

      <Card>
        {logsQuery.isLoading ? (
          <LoadingBlock label="Loading access history…" />
        ) : logsQuery.isError ? (
          <EmptyState
            icon="alert"
            title="Could not load access logs"
            description={apiErrorMessage(logsQuery.error)}
            action={<Button icon="refresh" onClick={() => void logsQuery.refetch()}>Retry</Button>}
          />
        ) : (logsQuery.data?.items ?? []).length === 0 ? (
          <EmptyState icon="logs" title="No access events match the filters" description="Try widening the date range or clearing the search." />
        ) : (
          <>
            <TableShell>
              <thead>
                <tr>
                  <Th>When</Th>
                  <Th>Plate / identity</Th>
                  <Th>Gate</Th>
                  <Th>Decision</Th>
                  <Th>Reason</Th>
                  <Th>Method</Th>
                  <Th align="right">Snapshot</Th>
                </tr>
              </thead>
              <tbody>
                {(logsQuery.data?.items ?? []).map((log) => {
                  const meta = DECISION_META[log.decision];
                  const snapshot = mediaUrl(log.snapshot_url ?? log.face_snapshot_url);
                  return (
                    <tr
                      key={log.id}
                      onClick={() => openDetail(log)}
                      className="cursor-pointer transition hover:bg-ink-50/70 dark:hover:bg-ink-800/30"
                    >
                      <Td className="whitespace-nowrap text-[11px] text-ink-500 dark:text-ink-400">
                        {formatDateTime(log.occurred_at)}
                        <p className="text-[10px] uppercase text-ink-300 dark:text-ink-600">{log.direction}</p>
                      </Td>
                      <Td>
                        <p className="font-mono text-xs font-semibold uppercase tracking-wide text-ink-900 dark:text-ink-100">{log.plate_number ?? "Face only"}</p>
                        <p className="text-[10px] text-ink-400">
                          {log.resident?.full_name ?? log.visitor?.full_name ?? "Unrecognised"}
                        </p>
                      </Td>
                      <Td className="text-xs">
                        {log.gate?.name ?? "—"}
                        <p className="text-[10px] text-ink-400">{log.gate?.code ?? ""}</p>
                      </Td>
                      <Td>
                        <div className="flex flex-col items-start gap-1">
                          <Badge tone={meta.tone} dot>{meta.label}</Badge>
                          {log.is_overridden ? <span className="text-[10px] font-medium text-amber-600 dark:text-amber-400">overridden</span> : null}
                        </div>
                      </Td>
                      <Td className="max-w-[240px]">
                        <p className="truncate text-xs">{log.reason}</p>
                        <p className="text-[10px] text-ink-400">{reasonLabel(log.reason_code)}</p>
                      </Td>
                      <Td>
                        <span className="rounded-md bg-ink-100 px-1.5 py-0.5 text-[10px] font-semibold uppercase text-ink-600 dark:bg-ink-800 dark:text-ink-300">{log.access_method}</span>
                        <p className="mt-0.5 text-[10px] text-ink-400">
                          {log.face_similarity !== null ? `face ${formatPercent(log.face_similarity)}` : log.plate_confidence !== null ? `plate ${formatPercent(log.plate_confidence)}` : ""}
                        </p>
                      </Td>
                      <Td align="right">
                        {snapshot ? (
                          <img src={snapshot} alt="Access snapshot" className="ml-auto h-9 w-14 rounded-md border border-ink-200 object-cover dark:border-ink-700" loading="lazy" />
                        ) : (
                          <span className="text-[10px] text-ink-300">—</span>
                        )}
                      </Td>
                    </tr>
                  );
                })}
              </tbody>
            </TableShell>
            {logsQuery.data ? (
              <Pagination
                page={logsQuery.data.page}
                pages={logsQuery.data.pages}
                total={logsQuery.data.total}
                pageSize={pageSize}
                onPageChange={setPage}
                onPageSizeChange={setPageSize}
              />
            ) : null}
          </>
        )}
      </Card>

      <Modal
        open={selected !== null}
        onClose={() => setSelected(null)}
        title="Access decision detail"
        description={selected ? `${selected.plate_number ?? "Pedestrian"} · ${formatDateTime(selected.occurred_at)}` : undefined}
        size="lg"
        footer={
          isManager && selected ? (
            <>
              <Button variant="outline" onClick={() => setSelected(null)}>Close</Button>
              <Button
                variant={overrideDecision === "allow" ? "primary" : "danger"}
                loading={overrideMutation.isPending}
                onClick={() => overrideMutation.mutate({ logId: selected.id })}
              >
                Apply override
              </Button>
            </>
          ) : (
            <Button variant="outline" onClick={() => setSelected(null)}>Close</Button>
          )
        }
      >
        {selected ? (
          <div className="space-y-4">
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone={DECISION_META[selected.decision].tone} dot>{DECISION_META[selected.decision].label}</Badge>
              <Badge tone={selected.gate_opened ? "success" : "neutral"}>{selected.gate_opened ? "Barrier opened" : "Barrier stayed closed"}</Badge>
              {selected.is_overridden ? <Badge tone="warning">Manual override</Badge> : null}
              <span className="text-[11px] text-ink-400">{reasonLabel(selected.reason_code)}</span>
            </div>

            {mediaUrl(selected.snapshot_url) ?? mediaUrl(selected.face_snapshot_url) ? (
              <img
                src={(mediaUrl(selected.snapshot_url) ?? mediaUrl(selected.face_snapshot_url))!}
                alt="Decision snapshot"
                className="w-full rounded-xl border border-ink-200 object-cover dark:border-ink-700"
              />
            ) : null}

            <dl className="grid gap-3 rounded-xl border border-ink-200 p-4 text-sm sm:grid-cols-2 dark:border-ink-700">
              <Detail label="Plate" value={selected.plate_number ?? "—"} mono />
              <Detail label="Gate" value={selected.gate?.name ?? "—"} />
              <Detail label="Direction" value={selected.direction} />
              <Detail label="Method" value={selected.access_method} />
              <Detail label="Resident" value={selected.resident?.full_name ?? "—"} />
              <Detail label="Visitor" value={selected.visitor?.full_name ?? "—"} />
              <Detail label="Permit" value={selected.permit?.permit_code ?? "—"} mono />
              <Detail label="Confidence" value={formatPercent(selected.plate_confidence ?? selected.face_similarity)} />
              <Detail label="Reason" value={selected.reason} />
              <Detail label="Camera" value={selected.camera?.name ?? "Uploaded frame"} />
            </dl>

            {selected.notes ? (
              <div className="rounded-xl bg-ink-50 p-3 text-xs text-ink-600 dark:bg-ink-900 dark:text-ink-300">
                <p className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-ink-400">Notes</p>
                {selected.notes}
              </div>
            ) : null}

            {isManager ? (
              <div className="rounded-xl border border-ink-200 p-4 dark:border-ink-700">
                <p className="text-xs font-semibold text-ink-800 dark:text-ink-100">Officer override</p>
                <div className="mt-3 grid gap-3 sm:grid-cols-2">
                  <Select label="New decision" value={overrideDecision} onChange={(event) => setOverrideDecision(event.target.value as AccessDecision)}>
                    <option value="allow">Allow</option>
                    <option value="deny">Deny</option>
                  </Select>
                  <label className="flex items-end gap-2 pb-2 text-xs text-ink-600 dark:text-ink-300">
                    <input
                      type="checkbox"
                      checked={overrideOpenGate}
                      onChange={(event) => setOverrideOpenGate(event.target.checked)}
                      disabled={overrideDecision !== "allow"}
                      className="h-4 w-4 rounded border-ink-300 text-brand-600 focus:ring-brand-500"
                    />
                    Open the barrier
                  </label>
                  <Textarea label="Override reason" required value={overrideReason} onChange={(event) => setOverrideReason(event.target.value)} className="sm:col-span-2" />
                </div>
              </div>
            ) : null}
          </div>
        ) : null}
      </Modal>

      <Modal
        open={manualOpen}
        onClose={() => setManualOpen(false)}
        title="Record a manual gate entry"
        description="Use this when the barrier is operated without a vision decision; the officer is recorded on the log."
        footer={
          <>
            <Button variant="outline" onClick={() => setManualOpen(false)}>Cancel</Button>
            <Button
              onClick={() => manualMutation.mutate()}
              loading={manualMutation.isPending}
              disabled={!manualForm.reason.trim() || manualForm.reason.trim().length < 3}
            >
              Record event
            </Button>
          </>
        }
      >
        <div className="grid gap-4 sm:grid-cols-2">
          <Select label="Gate" required value={manualForm.gate_id} onChange={(event) => setManualForm({ ...manualForm, gate_id: event.target.value })}>
            <option value="">Select a gate…</option>
            {gateOptions.map((gate) => (
              <option key={gate.id} value={gate.id}>{gate.name}</option>
            ))}
          </Select>
          <Select label="Direction" value={manualForm.direction} onChange={(event) => setManualForm({ ...manualForm, direction: event.target.value as AccessDirection })}>
            <option value="entry">Entry</option>
            <option value="exit">Exit</option>
          </Select>
          <Select label="Decision" value={manualForm.decision} onChange={(event) => setManualForm({ ...manualForm, decision: event.target.value as AccessDecision })}>
            <option value="allow">Allow</option>
            <option value="deny">Deny</option>
          </Select>
          <Input label="Plate" value={manualForm.plate_number} onChange={(event) => setManualForm({ ...manualForm, plate_number: event.target.value.toUpperCase() })} placeholder="Optional" className="font-mono" />
          <Input label="Reason" required value={manualForm.reason} onChange={(event) => setManualForm({ ...manualForm, reason: event.target.value })} className="sm:col-span-2" />
          <Textarea label="Notes" value={manualForm.notes} onChange={(event) => setManualForm({ ...manualForm, notes: event.target.value })} className="sm:col-span-2" />
        </div>
      </Modal>
    </div>
  );
}

function Detail({ label, value, mono = false }: { label: string; value: string; mono?: boolean }): JSX.Element {
  return (
    <div>
      <dt className="text-[10px] font-semibold uppercase tracking-wide text-ink-400">{label}</dt>
      <dd className={cn("mt-0.5 capitalize text-sm font-medium text-ink-800 dark:text-ink-100", mono && "font-mono uppercase")}>{value}</dd>
    </div>
  );
}
