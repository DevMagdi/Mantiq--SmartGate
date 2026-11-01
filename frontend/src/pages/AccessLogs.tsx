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
import { useI18n } from "@/i18n";
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
  const { t } = useI18n();
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
  const [overrideReason, setOverrideReason] = useState("");
  const [overrideOpenGate, setOverrideOpenGate] = useState(true);
  const [manualOpen, setManualOpen] = useState(false);
  const [manualForm, setManualForm] = useState({
    gate_id: "",
    direction: "entry" as AccessDirection,
    decision: "allow" as AccessDecision,
    plate_number: "",
    reason: "",
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
    onSuccess: (_data, format) => toast.success(t("logs.toast.export_ready", { format: format.toUpperCase() }), t("logs.toast.export_hint")),
    onError: (error) => toast.error(t("logs.toast.export_failed"), apiErrorMessage(error)),
  });

  const overrideMutation = useMutation({
    mutationFn: ({ logId }: { logId: string }) =>
      overrideAccessLog(logId, {
        decision: overrideDecision,
        reason: overrideReason,
        open_gate: overrideOpenGate && overrideDecision === "allow",
        notes: t("logs.manual.notes_default"),
      }),
    onSuccess: async (log) => {
      toast.success(t("logs.toast.decision_updated", { decision: t(`decision.${log.decision}`) }));
      setSelected(null);
      await queryClient.invalidateQueries({ queryKey: ["access-logs"] });
      await queryClient.invalidateQueries({ queryKey: ["dashboard"] });
    },
    onError: (error) => toast.error(t("logs.toast.override_failed"), apiErrorMessage(error)),
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
      toast.success(t("logs.toast.manual_recorded"));
      setManualOpen(false);
      setManualForm({
        gate_id: gateOptions[0]?.id ?? "",
        direction: "entry",
        decision: "allow",
        plate_number: "",
        reason: "",
        notes: "",
      });
      await queryClient.invalidateQueries({ queryKey: ["access-logs"] });
      await queryClient.invalidateQueries({ queryKey: ["dashboard"] });
    },
    onError: (error) => toast.error(t("logs.toast.manual_failed"), apiErrorMessage(error)),
  });

  const openDetail = (log: AccessLog): void => {
    setSelected(log);
    setOverrideDecision(log.decision === "deny" ? "allow" : "allow");
    setOverrideReason(
      log.decision === "deny" ? t("logs.manual.reason_granted") : t("logs.manual.reason_verified"),
    );
    setOverrideOpenGate(true);
  };

  const activeFilterCount = Object.values(filters).filter(Boolean).length;

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow={t("logs.eyebrow")}
        title={t("logs.title")}
        subtitle={t("logs.subtitle")}
        actions={
          <>
            <Button variant="outline" icon="download" onClick={() => exportMutation.mutate("csv")} loading={exportMutation.isPending && exportMutation.variables === "csv"}>
              CSV
            </Button>
            <Button variant="outline" icon="download" onClick={() => exportMutation.mutate("xlsx")} loading={exportMutation.isPending && exportMutation.variables === "xlsx"}>
              Excel
            </Button>
            {isManager ? (
              <Button icon="plus" onClick={() => { setManualForm((current) => ({ ...current, gate_id: current.gate_id || gateOptions[0]?.id || "", reason: current.reason || t("logs.manual.reason_default") })); setManualOpen(true); }}>
                {t("logs.manual_entry")}
              </Button>
            ) : null}
          </>
        }
      />

      <Card className="p-3">
        <div className="flex flex-wrap items-center gap-2">
          <SearchInput value={search} onChange={setSearch} placeholder={t("logs.search")} className="min-w-[220px] flex-1" />
          <Select value={filters.decision} onChange={(event) => setFilters({ ...filters, decision: event.target.value })} className="w-36">
            <option value="">{t("decision.all")}</option>
            <option value="allow">{t("decision.allow_verb")}</option>
            <option value="deny">{t("decision.deny_verb")}</option>
            <option value="unknown">{t("decision.unknown")}</option>
            <option value="review">{t("decision.review")}</option>
          </Select>
          <Button
            variant={showFilters ? "subtle" : "outline"}
            icon="filter"
            onClick={() => setShowFilters((current) => !current)}
          >
            {t("logs.filters")}{activeFilterCount > 0 ? ` · ${activeFilterCount}` : ""}
          </Button>
          {activeFilterCount > 0 ? (
            <Button variant="ghost" size="sm" onClick={() => setFilters(EMPTY_FILTERS)}>{t("common.reset")}</Button>
          ) : null}
          <Button variant="ghost" size="icon" onClick={() => void logsQuery.refetch()} aria-label={t("logs.refresh_aria")}>
            <Icon name="refresh" className={cn("h-4 w-4", logsQuery.isFetching && "animate-spin")} />
          </Button>
        </div>

        {showFilters ? (
          <div className="mt-3 grid gap-3 border-t border-ink-100 pt-3 sm:grid-cols-2 lg:grid-cols-5 dark:border-ink-800">
            <Input label={t("common.plate")} value={filters.plate} onChange={(event) => setFilters({ ...filters, plate: event.target.value.toUpperCase() })} placeholder="CAI 4821" />
            <Select label={t("common.direction")} value={filters.direction} onChange={(event) => setFilters({ ...filters, direction: event.target.value })}>
              <option value="">{t("direction.any")}</option>
              <option value="entry">{t("direction.entry")}</option>
              <option value="exit">{t("direction.exit")}</option>
            </Select>
            <Select label={t("common.gate")} value={filters.gateId} onChange={(event) => setFilters({ ...filters, gateId: event.target.value })}>
              <option value="">{t("logs.all_gates")}</option>
              {gateOptions.map((gate) => (
                <option key={gate.id} value={gate.id}>{gate.name}</option>
              ))}
            </Select>
            <Input label={t("logs.form.from")} type="date" value={filters.from} onChange={(event) => setFilters({ ...filters, from: event.target.value })} />
            <Input label={t("logs.form.to")} type="date" value={filters.to} onChange={(event) => setFilters({ ...filters, to: event.target.value })} />
            <Select label={t("logs.form.overridden")} value={filters.overridden} onChange={(event) => setFilters({ ...filters, overridden: event.target.value })}>
              <option value="">{t("logs.overridden.all")}</option>
              <option value="true">{t("logs.overridden.only")}</option>
              <option value="false">{t("logs.overridden.auto")}</option>
            </Select>
          </div>
        ) : null}
      </Card>

      <Card>
        {logsQuery.isLoading ? (
          <LoadingBlock label={t("logs.loading")} />
        ) : logsQuery.isError ? (
          <EmptyState
            icon="alert"
            title={t("logs.error_title")}
            description={apiErrorMessage(logsQuery.error)}
            action={<Button icon="refresh" onClick={() => void logsQuery.refetch()}>{t("common.retry")}</Button>}
          />
        ) : (logsQuery.data?.items ?? []).length === 0 ? (
          <EmptyState icon="logs" title={t("logs.empty_title")} description={t("logs.empty_desc")} />
        ) : (
          <>
            <TableShell>
              <thead>
                <tr>
                  <Th>{t("common.when")}</Th>
                  <Th>{t("logs.table.identity")}</Th>
                  <Th>{t("common.gate")}</Th>
                  <Th>{t("logs.table.decision")}</Th>
                  <Th>{t("common.reason")}</Th>
                  <Th>{t("common.method")}</Th>
                  <Th align="right">{t("logs.table.snapshot")}</Th>
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
                        <p className="font-mono text-xs font-semibold uppercase tracking-wide text-ink-900 dark:text-ink-100">{log.plate_number ?? t("logs.face_only")}</p>
                        <p className="text-[10px] text-ink-400">
                          {log.resident?.full_name ?? log.visitor?.full_name ?? t("logs.unrecognised")}
                        </p>
                      </Td>
                      <Td className="text-xs">
                        {log.gate?.name ?? "—"}
                        <p className="text-[10px] text-ink-400">{log.gate?.code ?? ""}</p>
                      </Td>
                      <Td>
                        <div className="flex flex-col items-start gap-1">
                          <Badge tone={meta.tone} dot>{t(`decision.${log.decision}`)}</Badge>
                          {log.is_overridden ? <span className="text-[10px] font-medium text-amber-600 dark:text-amber-400">{t("logs.overridden_badge")}</span> : null}
                        </div>
                      </Td>
                      <Td className="max-w-[240px]">
                        <p className="truncate text-xs">{log.reason}</p>
                        <p className="text-[10px] text-ink-400">{reasonLabel(log.reason_code)}</p>
                      </Td>
                      <Td>
                        <span className="rounded-md bg-ink-100 px-1.5 py-0.5 text-[10px] font-semibold uppercase text-ink-600 dark:bg-ink-800 dark:text-ink-300">{log.access_method}</span>
                        <p className="mt-0.5 text-[10px] text-ink-400">
                          {log.face_similarity !== null ? t("logs.face_confidence", { value: formatPercent(log.face_similarity) }) : log.plate_confidence !== null ? t("logs.plate_confidence", { value: formatPercent(log.plate_confidence) }) : ""}
                        </p>
                      </Td>
                      <Td align="right">
                        {snapshot ? (
                          <img src={snapshot} alt={t("logs.snapshot_alt")} className="ml-auto h-9 w-14 rounded-md border border-ink-200 object-cover dark:border-ink-700" loading="lazy" />
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
        title={t("logs.detail.title")}
        description={selected ? `${selected.plate_number ?? t("logs.detail.pedestrian")} · ${formatDateTime(selected.occurred_at)}` : undefined}
        size="lg"
        footer={
          isManager && selected ? (
            <>
              <Button variant="outline" onClick={() => setSelected(null)}>{t("common.close")}</Button>
              <Button
                variant={overrideDecision === "allow" ? "primary" : "danger"}
                loading={overrideMutation.isPending}
                onClick={() => overrideMutation.mutate({ logId: selected.id })}
              >
                {t("logs.detail.apply_override")}
              </Button>
            </>
          ) : (
            <Button variant="outline" onClick={() => setSelected(null)}>{t("common.close")}</Button>
          )
        }
      >
        {selected ? (
          <div className="space-y-4">
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone={DECISION_META[selected.decision].tone} dot>{t(`decision.${selected.decision}`)}</Badge>
              <Badge tone={selected.gate_opened ? "success" : "neutral"}>{selected.gate_opened ? t("logs.detail.barrier_opened") : t("logs.detail.barrier_closed")}</Badge>
              {selected.is_overridden ? <Badge tone="warning">{t("logs.detail.manual_override")}</Badge> : null}
              <span className="text-[11px] text-ink-400">{reasonLabel(selected.reason_code)}</span>
            </div>

            {mediaUrl(selected.snapshot_url) ?? mediaUrl(selected.face_snapshot_url) ? (
              <img
                src={(mediaUrl(selected.snapshot_url) ?? mediaUrl(selected.face_snapshot_url))!}
                alt={t("logs.snapshot_alt")}
                className="w-full rounded-xl border border-ink-200 object-cover dark:border-ink-700"
              />
            ) : null}

            <dl className="grid gap-3 rounded-xl border border-ink-200 p-4 text-sm sm:grid-cols-2 dark:border-ink-700">
              <Detail label={t("common.plate")} value={selected.plate_number ?? "—"} mono />
              <Detail label={t("common.gate")} value={selected.gate?.name ?? "—"} />
              <Detail label={t("common.direction")} value={t(`direction.${selected.direction}`)} />
              <Detail label={t("common.method")} value={selected.access_method} />
              <Detail label={t("common.resident")} value={selected.resident?.full_name ?? "—"} />
              <Detail label={t("common.visitor")} value={selected.visitor?.full_name ?? "—"} />
              <Detail label={t("visitors.table.permit")} value={selected.permit?.permit_code ?? "—"} mono />
              <Detail label={t("logs.detail.confidence")} value={formatPercent(selected.plate_confidence ?? selected.face_similarity)} />
              <Detail label={t("common.reason")} value={selected.reason} />
              <Detail label={t("common.camera")} value={selected.camera?.name ?? t("logs.detail.uploaded")} />
            </dl>

            {selected.notes ? (
              <div className="rounded-xl bg-ink-50 p-3 text-xs text-ink-600 dark:bg-ink-900 dark:text-ink-300">
                <p className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-ink-400">{t("common.notes")}</p>
                {selected.notes}
              </div>
            ) : null}

            {isManager ? (
              <div className="rounded-xl border border-ink-200 p-4 dark:border-ink-700">
                <p className="text-xs font-semibold text-ink-800 dark:text-ink-100">{t("logs.detail.officer")}</p>
                <div className="mt-3 grid gap-3 sm:grid-cols-2">
                  <Select label={t("logs.detail.new_decision")} value={overrideDecision} onChange={(event) => setOverrideDecision(event.target.value as AccessDecision)}>
                    <option value="allow">{t("decision.allow_verb")}</option>
                    <option value="deny">{t("decision.deny_verb")}</option>
                  </Select>
                  <label className="flex items-end gap-2 pb-2 text-xs text-ink-600 dark:text-ink-300">
                    <input
                      type="checkbox"
                      checked={overrideOpenGate}
                      onChange={(event) => setOverrideOpenGate(event.target.checked)}
                      disabled={overrideDecision !== "allow"}
                      className="h-4 w-4 rounded border-ink-300 text-brand-600 focus:ring-brand-500"
                    />
                    {t("logs.detail.open_barrier")}
                  </label>
                  <Textarea label={t("logs.detail.override_reason")} required value={overrideReason} onChange={(event) => setOverrideReason(event.target.value)} className="sm:col-span-2" />
                </div>
              </div>
            ) : null}
          </div>
        ) : null}
      </Modal>

      <Modal
        open={manualOpen}
        onClose={() => setManualOpen(false)}
        title={t("logs.manual.title")}
        description={t("logs.manual.description")}
        footer={
          <>
            <Button variant="outline" onClick={() => setManualOpen(false)}>{t("common.cancel")}</Button>
            <Button
              onClick={() => manualMutation.mutate()}
              loading={manualMutation.isPending}
              disabled={!manualForm.reason.trim() || manualForm.reason.trim().length < 3}
            >
              {t("logs.manual.record")}
            </Button>
          </>
        }
      >
        <div className="grid gap-4 sm:grid-cols-2">
          <Select label={t("common.gate")} required value={manualForm.gate_id} onChange={(event) => setManualForm({ ...manualForm, gate_id: event.target.value })}>
            <option value="">{t("logs.manual.select_gate")}</option>
            {gateOptions.map((gate) => (
              <option key={gate.id} value={gate.id}>{gate.name}</option>
            ))}
          </Select>
          <Select label={t("common.direction")} value={manualForm.direction} onChange={(event) => setManualForm({ ...manualForm, direction: event.target.value as AccessDirection })}>
            <option value="entry">{t("direction.entry")}</option>
            <option value="exit">{t("direction.exit")}</option>
          </Select>
          <Select label={t("logs.table.decision")} value={manualForm.decision} onChange={(event) => setManualForm({ ...manualForm, decision: event.target.value as AccessDecision })}>
            <option value="allow">{t("decision.allow_verb")}</option>
            <option value="deny">{t("decision.deny_verb")}</option>
          </Select>
          <Input label={t("common.plate")} value={manualForm.plate_number} onChange={(event) => setManualForm({ ...manualForm, plate_number: event.target.value.toUpperCase() })} placeholder={t("common.optional")} className="font-mono" />
          <Input label={t("common.reason")} required value={manualForm.reason} onChange={(event) => setManualForm({ ...manualForm, reason: event.target.value })} className="sm:col-span-2" />
          <Textarea label={t("common.notes")} value={manualForm.notes} onChange={(event) => setManualForm({ ...manualForm, notes: event.target.value })} className="sm:col-span-2" />
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
